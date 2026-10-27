"""
One-time maintenance: tag every existing node in `onefs_docs` with a `product`
metadata field so the assistants can be hard-walled by product.

  - Nodes already tagged product="insightiq" (added by ingest_insightiq.py) are left as-is.
  - Every other node gets product="onefs".

Metadata-only update (no re-embedding). Safe to re-run (idempotent).
Run:  python tag_products.py
"""
from pathlib import Path
import chromadb

DB_DIR = Path(__file__).parent / "app" / "chroma_db"

def main():
    col = chromadb.PersistentClient(path=str(DB_DIR)).get_collection("onefs_docs")
    got = col.get(include=["metadatas"])
    ids, metas = got["ids"], got["metadatas"]

    upd_ids, upd_metas = [], []
    for i, meta in zip(ids, metas):
        meta = dict(meta or {})
        if meta.get("product"):
            continue
        meta["product"] = "onefs"
        upd_ids.append(i)
        upd_metas.append(meta)

    print(f"total nodes: {len(ids)} | to tag onefs: {len(upd_ids)}")
    B = 1000
    for k in range(0, len(upd_ids), B):
        col.update(ids=upd_ids[k:k+B], metadatas=upd_metas[k:k+B])
        print(f"  tagged {min(k+B, len(upd_ids))}/{len(upd_ids)}")

    # verify
    onefs = len(col.get(where={"product": "onefs"}, include=[])["ids"])
    iiq   = len(col.get(where={"product": "insightiq"}, include=[])["ids"])
    print(f"DONE. product=onefs: {onefs} | product=insightiq: {iiq} | total: {col.count()}")

if __name__ == "__main__":
    main()
