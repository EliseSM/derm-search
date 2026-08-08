"""Embed the fetched abstracts and populate a persistent Chroma collection.

Usage:
    python ingest/build_index.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import (
    ABSTRACTS_PATH,
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
)


def main() -> None:
    if not ABSTRACTS_PATH.exists():
        raise SystemExit(
            f"{ABSTRACTS_PATH} not found. Run `python ingest/fetch_pubmed.py` first."
        )

    with open(ABSTRACTS_PATH, encoding="utf-8") as f:
        records = json.load(f)
    if not records:
        raise SystemExit("abstracts.json is empty — nothing to index.")

    # Imported lazily so the (heavy) ML deps only load when actually building.
    import chromadb
    from sentence_transformers import SentenceTransformer

    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    texts = [f"{r['title']}\n\n{r['abstract']}" for r in records]
    print(f"Embedding {len(texts)} abstracts...")
    embeddings = model.encode(
        texts, show_progress_bar=True, convert_to_numpy=True
    ).tolist()

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Rebuild cleanly so re-runs don't accumulate stale vectors.
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)

    collection.add(
        ids=[r["pmid"] for r in records],
        embeddings=embeddings,
        documents=[r["abstract"] for r in records],
        metadatas=[
            {
                "pmid": r["pmid"],
                "title": r["title"],
                "journal": r["journal"],
                "year": r["year"],
                "url": r["url"],
            }
            for r in records
        ],
    )

    print(f"\nIndexed {collection.count()} abstracts into "
          f"collection '{COLLECTION_NAME}' at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
