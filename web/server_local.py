"""
PowerScale AI Assistant — backend for both prototypes.

    /            OneFS WebUI assistant
    /insightiq   InsightIQ assistant

Two engines, same prompt (so the answers are identical):

  * in-process llama-cpp (default) — the LLM runs *inside* this Python process,
    so the whole app is one process with no separate model server. CPU-only.
  * Ollama (opt-in via USE_OLLAMA=1) — offloads to a local GPU when present, so
    a full cited answer comes back in ~12s instead of minutes. Falls back to the
    in-process engine if Ollama isn't running or lacks the models.

Run:  python web/server_local.py            (CPU)
      set USE_OLLAMA=1 && python ...         (GPU, see START-DEMO-GPU.bat)
"""
import json
import os
import threading
import urllib.request
from pathlib import Path

from flask import Flask, Response, request, send_from_directory

ROOT      = Path(__file__).parent
MODELS    = ROOT.parent / "models_gguf"
EMB_PATH  = MODELS / "nomic-embed-text.f16.gguf"
DB_DIR    = ROOT.parent / "app" / "chroma_db"

# GGUF the in-process (CPU) engine loads. A bundle ships exactly one of these;
# first present wins. Qwen2.5-3B is preferred: given the full excerpts it emits
# the `isi` CLI command in a fenced block, which llama3.2:3b never does. The
# fallbacks keep an un-updated bundle booting whatever model it already has.
LLM_CANDIDATES = [MODELS / "qwen2.5-3b-instruct.Q4_K_M.gguf",
                  MODELS / "llama3.2-3b-instruct.Q4_K_M.gguf",
                  MODELS / "llama3.1-8b-instruct.Q4_K_M.gguf"]
LLM_PATH  = next((p for p in LLM_CANDIDATES if p.exists()), LLM_CANDIDATES[0])

# Retrieval + prompt sizing. On CPU, prompt "prefill" dominates latency, so feed
# fewer/trimmed excerpts; on the GPU prefill is ~40x faster, so feed more, full
# excerpts (needed for the CLI command to survive intact — 1800 = whole chunk).
TOP_K            = int(os.environ.get("TOP_K", "5"))
TOP_K_GPU        = int(os.environ.get("TOP_K_GPU", "8"))
PROMPT_CHARS     = int(os.environ.get("PROMPT_CHARS", "1300"))
PROMPT_CHARS_GPU = int(os.environ.get("PROMPT_CHARS_GPU", "1800"))
MIN_SCORE        = 0.35
MAX_TOKENS       = 500

# CPU threads. Leave headroom for the OS and — on a PowerScale node — the storage
# workload, instead of grabbing every core (the "storage stays P0" governor).
# Override with N_THREADS (e.g. a big node might set a fixed cap).
N_THREADS = int(os.environ.get("N_THREADS", str(max(2, (os.cpu_count() or 4) - 2))))

# Engine selection. Ollama (GPU) is OPT-IN via USE_OLLAMA=1, so the CPU bundle
# behaves identically whether or not an Ollama tray happens to be running.
USE_OLLAMA         = os.environ.get("USE_OLLAMA", "").strip().lower() not in ("", "0", "false", "no")
OLLAMA_URL         = "http://localhost:11434"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
OLLAMA_CHAT_MODEL  = os.environ.get("OLLAMA_CHAT_MODEL", "qwen2.5:3b-instruct")
# preferred chat models, override first; dedup keeps the override from repeating
OLLAMA_MODEL_ORDER = list(dict.fromkeys(
    [OLLAMA_CHAT_MODEL, "qwen2.5:3b-instruct", "llama3.1:8b", "llama3.2:3b"]))
OLLAMA_NUM_CTX     = int(os.environ.get("OLLAMA_NUM_CTX", "4096"))

SYSTEM_PROMPT = (
    "You are an expert Dell PowerScale / OneFS 9.12 storage administrator assistant.\n"
    "Answer using ONLY the provided documentation excerpts. Be thorough, accurate, and practical. "
    "If the answer includes steps, number them clearly. When you refer to a location in the UI, "
    "name it as \"Menu > Item\".\n"
    "IMPORTANT: if the excerpts contain a relevant OneFS CLI command (for example one starting with "
    "\"isi \"), you MUST also show it, copied verbatim from the excerpts, in a fenced code block using "
    "triple backticks. Give both the WebUI steps and the CLI command whenever both are available.\n"
    "If the excerpts do not contain enough information to answer confidently, say exactly: "
    "\"I don't have sufficient information in the loaded documentation to answer this accurately.\" "
    "Never invent commands, values, or procedures that are not in the excerpts."
)

app = Flask(__name__)
_llm = None
_emb = None
_col = None
_backend = None          # "ollama" | "llamacpp"
_load_lock = threading.Lock()


def _ollama_models():
    """Names of models actually pulled in Ollama, or None if Ollama isn't up."""
    try:
        tags = json.load(urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2))
        return {m["name"] for m in tags.get("models", [])}
    except Exception:
        return None


def _has(name: str, have) -> bool:
    return name in have or f"{name}:latest" in have


def _pick_ollama_model(have):
    """First preferred chat model that is actually pulled; None if none are.

    Guards machines where Ollama has only some of the preferred models pulled —
    asking for a missing model would 404 instead of just working.
    """
    for name in OLLAMA_MODEL_ORDER:
        if _has(name, have):
            return name
    return None


def _post(path: str, payload: dict, timeout: int = 300):
    req = urllib.request.Request(f"{OLLAMA_URL}{path}",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def _load():
    """Load the retriever + engine once (idempotent; safe from concurrent callers)."""
    global _llm, _emb, _col, _backend, OLLAMA_CHAT_MODEL
    with _load_lock:
        if _backend is not None:
            return
        import chromadb

        have = _ollama_models() if USE_OLLAMA else None
        chat = _pick_ollama_model(have) if have is not None else None
        if have is not None and chat and _has(OLLAMA_EMBED_MODEL, have):
            _backend = "ollama"
            OLLAMA_CHAT_MODEL = chat
            print(f"Engine: Ollama at {OLLAMA_URL} (GPU if available) — model {chat}")
        else:
            if have is not None:
                print(f"Ollama is running but lacks the models it needs "
                      f"(want one of {OLLAMA_MODEL_ORDER} + {OLLAMA_EMBED_MODEL}); "
                      f"using the in-process engine instead.")
            _backend = "llamacpp"
            from llama_cpp import Llama
            chat_format = "chatml" if "qwen" in LLM_PATH.name.lower() else "llama-3"
            print(f"Engine: in-process llama-cpp (CPU, {N_THREADS} threads) — {LLM_PATH.name}")
            print("Loading embedding model...")
            _emb = Llama(model_path=str(EMB_PATH), embedding=True, n_ctx=2048,
                         n_threads=N_THREADS, verbose=False)
            print("Loading language model... this takes a moment")
            _llm = Llama(model_path=str(LLM_PATH), n_ctx=8192, n_threads=N_THREADS,
                         chat_format=chat_format, verbose=False)

        db = chromadb.PersistentClient(path=str(DB_DIR))
        _col = db.get_or_create_collection("onefs_docs")
        print("Ready.")


def _embed(text: str):
    if _backend == "ollama":
        r = json.load(_post("/api/embeddings",
                            {"model": OLLAMA_EMBED_MODEL, "prompt": text}, timeout=60))
        return r["embedding"]
    return _emb.create_embedding(text)["data"][0]["embedding"]


def _stream_answer(system: str, user: str):
    """Yield answer text chunks. Same prompt on both engines."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if _backend == "ollama":
        resp = _post("/api/chat", {
            "model": OLLAMA_CHAT_MODEL, "stream": True, "messages": messages,
            "options": {"temperature": 0.2, "num_predict": MAX_TOKENS, "num_ctx": OLLAMA_NUM_CTX},
        })
        for line in resp:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            tok = (ev.get("message") or {}).get("content")
            if tok:
                yield tok
            if ev.get("done"):
                break
    else:
        for chunk in _llm.create_chat_completion(
                messages=messages, stream=True, temperature=0.2, max_tokens=MAX_TOKENS):
            tok = chunk["choices"][0]["delta"].get("content")
            if tok:
                yield tok


def prettify(fname: str) -> str:
    return (fname.replace("onefs-9120-", "").replace("onefs-", "")
                 .replace("-", " ").replace(".pdf", "").title())


# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.route("/insightiq")
def insightiq():
    return send_from_directory(ROOT, "insightiq.html")


@app.route("/api/health")
def health():
    return {"ok": _col is not None, "engine": _backend}


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    context  = (data.get("context") or "").strip()
    if not question:
        return {"error": "empty question"}, 400

    # Hard wall: the OneFS WebUI assistant retrieves OneFS docs only; the
    # InsightIQ assistant retrieves everything (OneFS + InsightIQ) so that
    # explain-alert (OneFS Event Reference) and performance answers both work.
    product = (data.get("product") or "").strip().lower()
    if product not in ("onefs", "insightiq"):
        product = "insightiq" if "insightiq" in context.lower() else "onefs"
    where = {"product": "onefs"} if product == "onefs" else None

    def stream():
        try:
            _load()
            # 1) retrieve (more excerpts on the GPU, where prefill is nearly free)
            k = TOP_K_GPU if _backend == "ollama" else TOP_K
            qv = _embed(question)
            res = _col.query(query_embeddings=[qv], n_results=k, where=where,
                             include=["documents", "metadatas", "distances"])
            docs   = res["documents"][0]
            metas  = res["metadatas"][0]
            dists  = res["distances"][0]

            sources, seen, excerpts = [], set(), []
            for doc, meta, dist in zip(docs, metas, dists):
                sim = 1.0 - float(dist)
                excerpts.append(doc)
                fn = (meta or {}).get("file_name", "")
                if sim >= MIN_SCORE and fn and fn not in seen:
                    seen.add(fn)
                    sources.append(prettify(fn))

            pc = PROMPT_CHARS_GPU if _backend == "ollama" else PROMPT_CHARS
            ctx_block = "\n\n---\n\n".join(d[:pc] for d in excerpts)
            loc = f"(The user is currently viewing {context}.)\n" if context else ""
            user_msg = (f"{loc}Use ONLY these OneFS documentation excerpts to answer.\n\n"
                        f"{ctx_block}\n\nQuestion: {question}")

            # 2) generate (streamed) — same prompt on Ollama/GPU or llama-cpp/CPU
            full = ""
            for delta in _stream_answer(SYSTEM_PROMPT, user_msg):
                full += delta
                yield f"data: {json.dumps({'token': delta})}\n\n"

            if "sufficient information" in full.lower():
                sources = []
            yield f"data: {json.dumps({'sources': sources, 'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    # Warm up in the background so the pages serve instantly. On Ollama this is
    # near-instant; on the CPU engine the model loads once and stays resident,
    # so every answer (including the first) avoids a reload.
    print("Serving PowerScale WebUI + InsightIQ at http://localhost:8501")
    print("(warming up in the background...)")
    threading.Thread(target=_load, daemon=True).start()
    app.run(host="127.0.0.1", port=8501, threaded=True)
