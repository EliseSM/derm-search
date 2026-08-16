---
name: add-articles
description: Add N new PubMed dermatology abstracts on a specific skin topic to the local vector database. Use when the user wants to grow, expand, or top up the derm-search corpus/index — e.g. "add 25 psoriasis articles", "get 10 more melanoma papers into the vector DB", "index some eczema abstracts". Incremental: it never rebuilds the existing collection.
---

# Add articles to the vector database

Fetches new PubMed abstracts filtered to one skin topic, appends them to
`data/abstracts.json`, and embeds them into the existing Chroma collection.
This is additive — existing vectors are left alone (unlike
`ingest/build_index.py`, which wipes and rebuilds the collection).

## Arguments

Two things are needed. Both usually come straight from the user's request.

| Argument | Meaning | Example |
| --- | --- | --- |
| count | how many **new** articles to add | `25` |
| topic | the skin subject to restrict the search to | `plaque psoriasis` |

Parse them from the request (`/add-articles 25 psoriasis`, or prose like
"add 10 more articles about acne"). If either is missing, ask — do not guess a
count, and do not fall back to an unfiltered dermatology search.

Quote multi-word topics. A topic can be a condition (`hidradenitis
suppurativa`), a treatment (`dupilumab`), or a broader area (`skin cancer
screening`).

## Steps

1. Run the ingest script from the repo root:

   ```bash
   python ingest/add_articles.py --count <count> --topic "<topic>"
   ```

   Add `--dry-run` first if the user wants to preview which articles would be
   added before spending time on embedding.

2. Read the output and report back:
   - how many articles were actually added (may be fewer than requested — see below),
   - the new collection total,
   - the titles/PMIDs added, if the user cares which ones.

3. No restart is needed for retrieval to pick the new articles up on a fresh
   run, but a **running** `uvicorn app.main:app` server caches the collection
   handle in a module-level singleton (`app/rag.py:_get_collection`). If the app
   is already running, tell the user to restart it (or note that `--reload`
   picks it up on the next code change).

## What the script does

- Builds a PubMed term from the topic, constrained to dermatology MeSH terms,
  English, journal articles, and `hasabstract` — sorted by relevance.
- Skips any PMID already in `data/abstracts.json` **or** already in the Chroma
  collection, so re-running with the same topic keeps adding *different*
  articles instead of duplicating.
- Over-fetches candidates (6× the requested count) because many are already
  indexed or lack a usable abstract.
- Tags each new record with `topic` metadata, so added articles are
  distinguishable from the original seed corpus.
- Embeds with the same `EMBEDDING_MODEL` from `app/config.py` that the query
  side uses — do not override it here, or the new vectors won't be comparable
  to the old ones.

## Expected outcomes and gotchas

- **Fewer articles than requested.** Normal for narrow topics that are already
  well covered. The script says so explicitly. Relay that to the user and offer
  a broader topic rather than silently re-running.
- **"No new articles found".** Everything PubMed returned for that topic is
  already indexed. Suggest a broader or adjacent topic.
- Needs internet (PubMed E-utilities). `PUBMED_EMAIL` in `.env` is optional but
  polite; the script stays under NCBI's ~3 req/s limit either way.
- First run in a fresh checkout downloads the sentence-transformers model, so
  it takes noticeably longer.
- If `data/chroma/` doesn't exist yet, the script creates the collection —
  but a normal first-time setup should use
  `ingest/fetch_pubmed.py` + `ingest/build_index.py` per the README.
