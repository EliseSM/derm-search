"""Add N more PubMed abstracts on a given skin topic to the existing index.

Unlike `build_index.py` (which rebuilds the whole collection from scratch), this
script is *incremental*: it skips PMIDs already present, appends only the new
records to data/abstracts.json, and embeds just those into the existing Chroma
collection.

Usage:
    python ingest/add_articles.py --count 25 --topic "plaque psoriasis"
    python ingest/add_articles.py --count 10 --topic eczema --dry-run
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import (  # noqa: E402
    ABSTRACTS_PATH,
    CHROMA_DIR,
    COLLECTION_NAME,
    DATA_DIR,
    EMBEDDING_MODEL,
    PUBMED_URL_TEMPLATE,
)
# Reuse the PubMed plumbing (search params, XML parsing, rate limiting).
from fetch_pubmed import (  # noqa: E402
    BATCH_SIZE,
    EUTILS,
    REQUEST_INTERVAL,
    _COMMON_PARAMS,
    _parse_article,
)

import requests  # noqa: E402

# Keep the topic query inside dermatology and require a usable abstract.
TOPIC_TERM_TEMPLATE = (
    '({topic}) AND (dermatology[MeSH Terms] OR skin[MeSH Terms] OR '
    'skin diseases[MeSH Terms] OR ({topic})) AND hasabstract[text] '
    'AND English[Language] AND journal article[Publication Type]'
)
# Over-fetch candidates: many PMIDs are already indexed or lack an abstract.
CANDIDATE_MULTIPLIER = 6
MAX_CANDIDATES = 1000


def esearch_topic(topic: str, retmax: int) -> list[str]:
    """Relevance-sorted PMIDs for a skin topic."""
    term = TOPIC_TERM_TEMPLATE.format(topic=topic)
    print(f"Searching PubMed: {term!r}")
    resp = requests.get(
        f"{EUTILS}/esearch.fcgi",
        params={**_COMMON_PARAMS, "term": term, "retmax": retmax,
                "retmode": "json", "sort": "relevance"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["esearchresult"]["idlist"]


def load_existing() -> list[dict]:
    if not ABSTRACTS_PATH.exists():
        return []
    with open(ABSTRACTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def indexed_ids() -> set[str]:
    """PMIDs already in the Chroma collection (empty if there is no store yet)."""
    if not CHROMA_DIR.exists():
        return set()
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_collection(COLLECTION_NAME)
        return set(collection.get(include=[])["ids"])
    except Exception:
        return set()


def fetch_until(pmids: list[str], want: int, topic: str) -> list[dict]:
    """efetch candidate PMIDs in batches, stopping once `want` are usable."""
    records: list[dict] = []
    for start in range(0, len(pmids), BATCH_SIZE):
        batch = pmids[start:start + BATCH_SIZE]
        resp = requests.get(
            f"{EUTILS}/efetch.fcgi",
            params={**_COMMON_PARAMS, "id": ",".join(batch),
                    "rettype": "abstract", "retmode": "xml"},
            timeout=60,
        )
        resp.raise_for_status()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
        for article in root.findall(".//PubmedArticle"):
            rec = _parse_article(article)
            if rec:
                rec["topic"] = topic
                rec["url"] = PUBMED_URL_TEMPLATE.format(pmid=rec["pmid"])
                records.append(rec)
        print(f"  fetched {min(start + BATCH_SIZE, len(pmids))}/{len(pmids)} "
              f"candidates -> {len(records)} usable so far")
        if len(records) >= want:
            break
        time.sleep(REQUEST_INTERVAL)
    return records[:want]


def embed_and_add(records: list[dict]) -> int:
    """Embed the new records and add them to the persistent collection."""
    import chromadb
    from sentence_transformers import SentenceTransformer

    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    texts = [f"{r['title']}\n\n{r['abstract']}" for r in records]
    print(f"Embedding {len(texts)} new abstracts...")
    embeddings = model.encode(
        texts, show_progress_bar=True, convert_to_numpy=True
    ).tolist()

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(COLLECTION_NAME)
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
                "topic": r["topic"],
            }
            for r in records
        ],
    )
    return collection.count()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add N PubMed abstracts on a skin topic to the vector DB."
    )
    parser.add_argument("--count", type=int, required=True,
                        help="how many NEW articles to add")
    parser.add_argument("--topic", required=True,
                        help='skin subject, e.g. "plaque psoriasis" or melanoma')
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be added; write nothing")
    args = parser.parse_args()

    if args.count < 1:
        raise SystemExit("--count must be at least 1")

    existing = load_existing()
    seen = {r["pmid"] for r in existing} | indexed_ids()
    print(f"{len(existing)} abstracts in {ABSTRACTS_PATH.name}, "
          f"{len(seen)} PMIDs already known")

    retmax = min(max(args.count * CANDIDATE_MULTIPLIER, args.count + 50),
                 MAX_CANDIDATES)
    candidates = esearch_topic(args.topic, retmax)
    fresh = [p for p in candidates if p not in seen]
    print(f"{len(candidates)} candidates, {len(fresh)} not yet indexed")
    if not fresh:
        raise SystemExit(
            f"No new articles found for {args.topic!r}. Try a broader topic."
        )
    time.sleep(REQUEST_INTERVAL)

    records = fetch_until(fresh, args.count, args.topic)
    if not records:
        raise SystemExit(f"No usable abstracts found for {args.topic!r}.")

    print(f"\n{len(records)} new article(s) on {args.topic!r}:")
    for r in records:
        print(f"  [{r['pmid']}] {r['year']} — {r['title'][:90]}")

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    total = embed_and_add(records)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ABSTRACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(existing + records, f, ensure_ascii=False, indent=2)

    print(f"\nAdded {len(records)} abstracts on {args.topic!r}. "
          f"Collection '{COLLECTION_NAME}' now holds {total}; "
          f"{ABSTRACTS_PATH.name} holds {len(existing) + len(records)}.")
    if len(records) < args.count:
        print(f"NOTE: asked for {args.count} but only {len(records)} new usable "
              "article(s) were available for this topic.")


if __name__ == "__main__":
    main()
