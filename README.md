# derm-search

A simple, transparent **RAG** (Retrieval-Augmented Generation) system over ~200
PubMed dermatology abstracts. It runs locally, **cites the source article** for
every claim, and shows each RAG step live in the browser as it happens.

- **Retrieval is fully local** — abstracts are embedded with a local
  sentence-transformers model and stored in a local ChromaDB.
- **Answer generation** uses the Claude API (`claude-opus-4-8`) with Claude's
  native **citations** feature, so each sentence is tied to a specific abstract.
- **Frontend** is a small FastAPI + Server-Sent-Events page showing the pipeline
  (embed → search → retrieve → generate), the streamed answer, and citation cards
  that link back to PubMed.

## Architecture

```
Ingestion (one-time, needs internet)
  ingest/fetch_pubmed.py ──> data/abstracts.json   (PMID, title, authors, journal, year, abstract, url)
  ingest/build_index.py  ──> data/chroma/          (local embeddings in ChromaDB)

Query (local retrieval + one Claude call)
  Browser (EventSource) ──SSE──> FastAPI /api/query
      embed query → search vectors → retrieved abstracts
      → Claude generates a cited answer (abstracts passed as `document` blocks)
      → streamed answer + citation cards linking to PubMed
```

Each abstract is short, so **one abstract = one embedding = one Claude document
block**. Top-k retrieval picks which abstracts to send; Claude's citation engine
attributes each claim to a document, which the app maps back to a PMID/URL.

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt

# Auth for the answer step. Either export a key:
#   ANTHROPIC_API_KEY=sk-...
# or run `ant auth login` (the SDK resolves the profile automatically).
cp .env.example .env   # then edit .env, or set the env var directly
```

## Run

```bash
# 1. Fetch abstracts from PubMed (one-time, needs internet)
python ingest/fetch_pubmed.py

# 2. Build the local vector index
python ingest/build_index.py

# 3. Start the app
uvicorn app.main:app --reload
```

Open <http://localhost:8000> and ask a dermatology question, e.g.
*"What are treatment options for plaque psoriasis?"*

## Growing the corpus

To add more abstracts on a specific skin topic without rebuilding the index:

```bash
python ingest/add_articles.py --count 25 --topic "plaque psoriasis"
python ingest/add_articles.py --count 10 --topic eczema --dry-run   # preview only
```

New PMIDs are appended to `data/abstracts.json`, embedded with the same model,
and added to the existing Chroma collection; already-indexed PMIDs are skipped.
Restart the server afterwards — `app/rag.py` caches the collection handle.
The `/add-articles` skill in `.claude/skills/` wraps this for Claude Code.

## Notes

- **Embedding model:** defaults to `sentence-transformers/all-MiniLM-L6-v2`
  (fast, CPU-friendly). For stronger biomedical relevance, set
  `EMBEDDING_MODEL = "pritamdeka/S-PubMedBert-MS-MARCO"` in `app/config.py` and
  re-run `python ingest/build_index.py` (the query side reads the same constant).
- **What's local vs. not:** ingestion hits PubMed once; at query time the only
  external call is to `api.anthropic.com` for generation. Embedding and vector
  search are fully local.
- `data/` (abstracts + vector store) and `.env` are gitignored.

## Layout

```
ingest/fetch_pubmed.py   PubMed E-utilities → data/abstracts.json
ingest/build_index.py    embed abstracts → data/chroma/ (full rebuild)
ingest/add_articles.py   add N more abstracts on one skin topic (incremental)
app/config.py            paths, model names, top_k
app/rag.py               retrieval + Claude streaming with citations
app/main.py              FastAPI app + SSE endpoint
static/                  index.html, app.js (EventSource), styles.css
```
