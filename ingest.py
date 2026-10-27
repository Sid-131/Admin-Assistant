"""
OneFS 9.12 RAG Ingestion Script
Run this ONCE on your machine to build the vector database from the downloaded PDFs.
Usage: python ingest.py
"""

import os
import sys
from pathlib import Path

DOCS_DIR  = Path(__file__).parent / "docs"
DB_DIR    = Path(__file__).parent / "app" / "chroma_db"
OLLAMA_URL = "http://localhost:11434"

def check_ollama():
    import urllib.request
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5)
        return True
    except Exception:
        return False

def main():
    print("\n" + "="*55)
    print("  OneFS 9.12 RAG Ingestion")
    print("="*55)

    # Check Ollama is running
    if not check_ollama():
        print("\n[ERROR] Ollama is not running.")
        print("  Start it with:  ollama serve")
        print("  Then re-run this script.")
        sys.exit(1)
    print("[OK] Ollama is running")

    # Check docs exist
    pdfs = list(DOCS_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"\n[ERROR] No PDFs found in: {DOCS_DIR}")
        print("  Run download_docs.ps1 first.")
        sys.exit(1)
    print(f"[OK] Found {len(pdfs)} PDFs in docs/")
    for p in pdfs:
        size = p.stat().st_size / (1024*1024)
        print(f"     {p.name} ({size:.1f} MB)")

    # Imports after checks
    try:
        from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, Settings
        from llama_index.core.node_parser import SentenceSplitter
        from llama_index.embeddings.ollama import OllamaEmbedding
        from llama_index.vector_stores.chroma import ChromaVectorStore
        from llama_index.core import StorageContext
        import chromadb
    except ImportError as e:
        print(f"\n[ERROR] Missing package: {e}")
        print("  Run: pip install -r requirements.txt")
        sys.exit(1)

    print("\n[1/4] Loading PDFs...")
    reader = SimpleDirectoryReader(
        input_dir=str(DOCS_DIR),
        required_exts=[".pdf"],
        filename_as_id=True,
    )
    documents = reader.load_data()
    print(f"      Loaded {len(documents)} document chunks from {len(pdfs)} PDFs")

    print("\n[2/4] Setting up embedding model (nomic-embed-text)...")
    embed_model = OllamaEmbedding(
        model_name="nomic-embed-text",
        base_url=OLLAMA_URL,
        request_timeout=60.0,
        # nomic-embed-text natively supports an 8192-token context, but Ollama
        # defaults to 2048 and errors out on long chunks. Use the full context.
        ollama_additional_kwargs={"num_ctx": 8192},
    )
    Settings.embed_model = embed_model
    Settings.llm = None  # No LLM needed at ingestion time

    print("\n[3/4] Chunking documents...")
    splitter = SentenceSplitter(
        chunk_size=512,
        chunk_overlap=64,
    )
    nodes = splitter.get_nodes_from_documents(documents, show_progress=True)
    print(f"      Created {len(nodes)} chunks")

    # nomic-embed-text is architecturally capped at 2048 tokens, and this
    # version of llama-index uses Ollama's /api/embeddings endpoint, which does
    # not auto-truncate. Dense pages (CLI tables, file paths, symbol-heavy text)
    # can tokenize into more wordpiece tokens than their 512 "tiktoken" size and
    # blow past 2048. Since each wordpiece token is >= 1 character, capping the
    # text at ~1800 chars guarantees we stay under the limit even worst-case.
    MAX_CHARS = 1800
    truncated = 0
    for n in nodes:
        # Tag every OneFS chunk so the WebUI assistant can be hard-walled to
        # OneFS-only retrieval (InsightIQ docs are tagged product="insightiq"
        # by ingest_insightiq.py). See tag_products.py for retro-tagging.
        n.metadata["product"] = "onefs"
        if len(n.text) > MAX_CHARS:
            n.text = n.text[:MAX_CHARS]
            truncated += 1
    if truncated:
        print(f"      Truncated {truncated} oversized chunks to {MAX_CHARS} chars")

    print("\n[4/4] Building vector store...")
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db     = chromadb.PersistentClient(path=str(DB_DIR))
    # Use cosine distance so retrieval scores are real cosine similarities in
    # [0,1]. Without this, Chroma defaults to L2 and scores are meaningless,
    # which would break the app's source-citation threshold.
    col    = db.get_or_create_collection(
        "onefs_docs", metadata={"hnsw:space": "cosine"}
    )
    vstore = ChromaVectorStore(chroma_collection=col)
    ctx    = StorageContext.from_defaults(vector_store=vstore)

    VectorStoreIndex(nodes, storage_context=ctx, show_progress=True)

    print("\n" + "="*55)
    print(f"  Ingestion complete!")
    print(f"  Vector DB saved to: {DB_DIR}")
    print(f"  Chunks indexed: {len(nodes)}")
    print("="*55 + "\n")

if __name__ == "__main__":
    main()
