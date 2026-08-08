"""Fetch ~200 dermatology abstracts from PubMed E-utilities.

One-time, requires internet. Writes data/abstracts.json — a list of records:
{pmid, title, abstract, authors, journal, year, url}

Usage:
    python ingest/fetch_pubmed.py
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from dotenv import load_dotenv

# Make `app` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import ABSTRACTS_PATH, DATA_DIR, FETCH_COUNT, PUBMED_URL_TEMPLATE

load_dotenv()

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# Dermatology, English, journal articles that actually carry an abstract.
SEARCH_TERM = (
    'dermatology[MeSH Terms] AND hasabstract[text] '
    'AND English[Language] AND journal article[Publication Type]'
)
# Be polite to NCBI: without an API key, keep to ~3 requests/second.
REQUEST_INTERVAL = 0.34
BATCH_SIZE = 100

_COMMON_PARAMS = {"db": "pubmed", "tool": "derm-search"}
_email = os.getenv("PUBMED_EMAIL")
if _email:
    _COMMON_PARAMS["email"] = _email


def esearch(term: str, retmax: int) -> list[str]:
    resp = requests.get(
        f"{EUTILS}/esearch.fcgi",
        params={**_COMMON_PARAMS, "term": term, "retmax": retmax, "retmode": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["esearchresult"]["idlist"]


def _text(elem, path: str) -> str:
    node = elem.find(path)
    return node.text.strip() if node is not None and node.text else ""


def _parse_article(article) -> dict | None:
    pmid = _text(article, ".//PMID")
    if not pmid:
        return None

    title = "".join(article.find(".//ArticleTitle").itertext()).strip() \
        if article.find(".//ArticleTitle") is not None else ""

    # Abstracts may be split into multiple labeled sections; join them.
    parts = []
    for chunk in article.findall(".//Abstract/AbstractText"):
        label = chunk.get("Label")
        text = "".join(chunk.itertext()).strip()
        if not text:
            continue
        parts.append(f"{label}: {text}" if label else text)
    abstract = "\n\n".join(parts)
    if not abstract:
        return None  # skip records with no abstract

    authors = []
    for author in article.findall(".//AuthorList/Author"):
        last = _text(author, "LastName")
        initials = _text(author, "Initials")
        if last:
            authors.append(f"{last} {initials}".strip())

    journal = _text(article, ".//Journal/Title")
    year = _text(article, ".//JournalIssue/PubDate/Year") or \
        _text(article, ".//JournalIssue/PubDate/MedlineDate")[:4]

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "year": year,
        "url": PUBMED_URL_TEMPLATE.format(pmid=pmid),
    }


def efetch(pmids: list[str]) -> list[dict]:
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
        root = ET.fromstring(resp.content)
        for article in root.findall(".//PubmedArticle"):
            rec = _parse_article(article)
            if rec:
                records.append(rec)
        print(f"  fetched {min(start + BATCH_SIZE, len(pmids))}/{len(pmids)} "
              f"PMIDs -> {len(records)} usable so far")
        time.sleep(REQUEST_INTERVAL)
    return records


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Over-fetch a little because some records lack a usable abstract.
    print(f"Searching PubMed: {SEARCH_TERM!r}")
    pmids = esearch(SEARCH_TERM, retmax=int(FETCH_COUNT * 1.5))
    print(f"Found {len(pmids)} candidate PMIDs; fetching abstracts...")
    time.sleep(REQUEST_INTERVAL)

    records = efetch(pmids)[:FETCH_COUNT]

    with open(ABSTRACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\nWrote {len(records)} abstracts to {ABSTRACTS_PATH}")
    if len(records) < FETCH_COUNT:
        print(f"NOTE: fewer than {FETCH_COUNT} usable abstracts. Widen SEARCH_TERM "
              "or raise the over-fetch multiplier if you need exactly 200.")


if __name__ == "__main__":
    main()
