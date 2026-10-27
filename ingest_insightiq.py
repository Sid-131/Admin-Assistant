"""
Incremental ingestion: add InsightIQ knowledge to the existing chroma_db.

Adds, into the SAME `onefs_docs` collection (so no server changes are needed):
  1. InsightIQ 6.2 Administration Guide  (conceptual grounding for performance)
  2. Any "Node Performance" scheduled reports you export from your own
     InsightIQ, reformatted into clean, self-describing text nodes that keep the
     per-node data + InsightIQ's own metric definitions (the raw PDF text is
     jumbled tables + chart images). None are shipped with this repo.

New nodes are tagged  product="insightiq"  so they can be filtered later.
Existing OneFS vectors are left untouched (this appends).

Put the PDFs in docs/insightiq/ (or set IIQ_DIR), start Ollama, then:
    python ingest_insightiq.py
"""
import os
import re
import sys
import unicodedata
from pathlib import Path

from pypdf import PdfReader

ROOT   = Path(__file__).parent
DB_DIR = ROOT / "app" / "chroma_db"
IIQ    = Path(os.environ.get("IIQ_DIR", ROOT / "docs" / "insightiq"))
OLLAMA_URL = "http://localhost:11434"
MAX_CHARS  = 1800

ADMIN_620 = IIQ / "IIQ_620_Admin_Guide.pdf"
REPORTS = sorted(IIQ.glob("*node_performance*.pdf"))

METRIC_TITLES = [
    "External Network Throughput Rate",
    "Protocol Operations Rate",
    "CPU % Use",
    "Disk Throughput Rate",
    "Disk Operations Rate",
    "Active Clients",
    "Connected Clients",
]


# ── Report parsing ────────────────────────────────────────────────────────────
def parse_report(path: Path) -> dict:
    r = PdfReader(str(path))
    pages = [(pg.extract_text() or "") for pg in r.pages]
    text_all = "\n".join(pages)

    def grab(pattern, default=""):
        m = re.search(pattern, text_all)
        return m.group(1).strip() if m else default

    meta = {
        "title":   grab(r"\n([A-Za-z0-9_]+ Performance)\n") or "Node Performance",
        "server":  grab(r"InsightIQ Server:\s*([^\n]+)"),
        "cluster": grab(r"Cluster:\s*([^\n]+)"),
        "period":  grab(r"Reporting Period:\s*([^\n]+)"),
        "freq":    grab(r"Report Frequency:\s*([^\n]+)"),
    }

    # Node Summary table (page 2): rows "<node> <6 measurements>"
    nodes = []
    for pg in pages:
        if "Node Summary" not in pg:
            continue
        for line in pg.splitlines():
            m = re.match(r"^\s*(\d+)\s+(.+)$", line)
            if not m:
                continue
            measures = re.findall(r"([\d.]+)\s*([KMG]?b/s)", m.group(2))
            if len(measures) >= 6:
                vals = [f"{v} {u}" for v, u in measures[:6]]
                nodes.append((m.group(1), vals))
        break

    # CPU % Use page: "<node> <pct>%"
    cpu = []
    for pg in pages:
        if pg.strip().startswith("CPU % Use"):
            for line in pg.splitlines():
                m = re.match(r"^\s*(\d+)\s+([\d.]+)%\s*$", line)
                if m:
                    cpu.append((m.group(1), float(m.group(2))))
            break

    # Active Clients protocol breakout (real protocol names, not truncated IPs)
    protos = []
    grab_proto = False
    for pg in pages:
        if pg.strip().startswith("Active Clients") or grab_proto:
            grab_proto = True
            for line in pg.splitlines():
                m = re.match(r"^\s*([a-z][a-z0-9]+)\s+([\d.]+)%\s*$", line)
                if m:
                    protos.append((m.group(1), float(m.group(2))))
        if grab_proto and pg.strip().startswith("Connected Clients"):
            break

    return {"meta": meta, "nodes": nodes, "cpu": cpu, "protos": protos}


def report_summary_text(rp: dict) -> str:
    m = rp["meta"]
    lines = [
        f'InsightIQ Performance Report — "{m["title"]}"',
        f'Cluster: {m["cluster"]} | InsightIQ Server: {m["server"]}',
        f'Reporting period: {m["period"]} | Frequency: {m["freq"]}',
        "",
        "Per-node throughput (network In / Out / Total I/O, and Disk In / Out / Total Disk I/O):",
    ]
    cols = ["net in", "net out", "net total", "disk in", "disk out", "disk total"]
    for node, vals in sorted(rp["nodes"], key=lambda x: int(x[0])):
        parts = ", ".join(f"{c} {v}" for c, v in zip(cols, vals))
        lines.append(f"- Node {node}: {parts}")
    if rp["cpu"]:
        ranked = sorted(rp["cpu"], key=lambda x: x[1], reverse=True)
        cpu_str = ", ".join(f"Node {n} {p:.2f}%" for n, p in ranked)
        lines += ["", f"Average CPU % use by node (highest first): {cpu_str}."]
        top = ranked[0][0]
        lines.append(f"Node {top} was the busiest node (highest average CPU usage).")
    return "\n".join(lines)


# Metric definitions are identical across the 4 reports (same report type), so
# capture them once from report 1 and store one focused node per metric — leading
# with the metric name so a "what does <metric> mean" query matches it directly.
def metric_definition_texts(sample: Path, protos) -> list[tuple[str, str]]:
    r = PdfReader(str(sample))
    pages = [(pg.extract_text() or "") for pg in r.pages]
    defs = {}
    for pg in pages:
        head = pg.strip().splitlines()[0].strip() if pg.strip() else ""
        for title in METRIC_TITLES:
            if head == title:
                body = []
                for line in pg.splitlines()[1:]:
                    s = line.strip()
                    if not s or s.startswith("Breakout For") or s.startswith("More Details"):
                        continue
                    if s.endswith("%"):   # skip breakout rows ("siq 76.66%", "ffff:…1.52%")
                        continue
                    body.append(s)
                defs[title] = unicodedata.normalize("NFKC", " ".join(body)).strip()

    proto_str = ", ".join(f"{p} {v:.0f}%" for p, v in protos if v > 0) or "siq, papi"
    out = []
    for t in METRIC_TITLES:
        d = defs.get(t, "")
        text = (f'InsightIQ node performance report metric — "{t}": {d} '
                f'This is one of the metrics shown in an InsightIQ node performance report.')
        if t == "Active Clients":
            text += f" Active clients are broken out by protocol; a typical breakout is {proto_str}."
        slug = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
        out.append((slug, text))
    return out


def main():
    # sanity
    import urllib.request
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5)
    except Exception:
        print("[ERROR] Ollama not running. Start it, then re-run.")
        sys.exit(1)
    for p in [ADMIN_620, *REPORTS]:
        if not p.exists():
            print(f"[ERROR] missing: {p}")
            sys.exit(1)

    from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, Settings, StorageContext
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.schema import TextNode
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.vector_stores.chroma import ChromaVectorStore
    import chromadb

    Settings.embed_model = OllamaEmbedding(
        model_name="nomic-embed-text", base_url=OLLAMA_URL, request_timeout=60.0,
        ollama_additional_kwargs={"num_ctx": 8192},
    )
    Settings.llm = None

    all_nodes = []

    # 1) Admin guide
    print("[1/3] Loading InsightIQ 6.2 Administration Guide...")
    docs = SimpleDirectoryReader(input_files=[str(ADMIN_620)], filename_as_id=True).load_data()
    admin_nodes = SentenceSplitter(chunk_size=512, chunk_overlap=64).get_nodes_from_documents(docs)
    for n in admin_nodes:
        n.metadata["file_name"] = "InsightIQ 6.2 Administration Guide"
        n.metadata["product"]   = "insightiq"
    print(f"      {len(admin_nodes)} chunks")
    all_nodes.extend(admin_nodes)

    # 2) Report summaries (one per exported report)
    print("[2/3] Reformatting performance reports...")
    for rpt in REPORTS:
        rp = parse_report(rpt)
        node = TextNode(
            text=report_summary_text(rp),
            id_=f"iiq-report-{rpt.stem}",
            metadata={"file_name": f'InsightIQ Performance Report ({rp["meta"]["cluster"]})',
                      "product": "insightiq", "source_type": "performance_report",
                      "period": rp["meta"]["period"]},
        )
        all_nodes.append(node)
        print(f"      {rpt.name}: {len(rp['nodes'])} nodes, {len(rp['cpu'])} CPU rows")

    # 3) Shared metric definitions (one focused node per metric, deduplicated)
    if not REPORTS:
        print(f"      no *node_performance*.pdf found in {IIQ}; skipping reports")
    else:
        proto_all = parse_report(REPORTS[0])["protos"]
        for slug, txt in metric_definition_texts(REPORTS[0], proto_all):
            all_nodes.append(TextNode(
                text=txt, id_=f"iiq-metric-{slug}",
                metadata={"file_name": "InsightIQ Performance Metrics Reference",
                          "product": "insightiq", "source_type": "performance_report"}))

    # cap oversized chunks (nomic 2048-token limit safeguard)
    trunc = 0
    for n in all_nodes:
        if len(n.text) > MAX_CHARS:
            n.text = n.text[:MAX_CHARS]
            trunc += 1
    print(f"[3/3] Embedding + appending {len(all_nodes)} nodes "
          f"({trunc} truncated) into onefs_docs...")

    db  = chromadb.PersistentClient(path=str(DB_DIR))
    col = db.get_or_create_collection("onefs_docs", metadata={"hnsw:space": "cosine"})
    before = col.count()
    vstore = ChromaVectorStore(chroma_collection=col)
    ctx    = StorageContext.from_defaults(vector_store=vstore)
    VectorStoreIndex(all_nodes, storage_context=ctx, show_progress=True)
    after = col.count()

    print("\n" + "=" * 55)
    print(f"  Done. onefs_docs: {before} -> {after}  (+{after - before})")
    print("=" * 55)


if __name__ == "__main__":
    main()
