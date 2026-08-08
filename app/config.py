"""Shared configuration for the dermatology RAG.

Paths are anchored to the repo root so scripts work regardless of the current
working directory.
"""
from pathlib import Path

# repo root = parent of the `app/` package
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
ABSTRACTS_PATH = DATA_DIR / "abstracts.json"
CHROMA_DIR = DATA_DIR / "chroma"

# Chroma collection name (must match between build_index.py and rag.py)
COLLECTION_NAME = "derm_abstracts"

# Local embedding model. all-MiniLM-L6-v2 is fast and CPU-friendly (384-dim).
# For stronger biomedical relevance, swap to "pritamdeka/S-PubMedBert-MS-MARCO"
# and rebuild the index (the query side reads this same constant, so they stay
# in sync automatically).
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Number of abstracts to fetch and to retrieve per query.
FETCH_COUNT = 200
TOP_K = 6

# Answer-generation model.
CLAUDE_MODEL = "claude-opus-4-8"
MAX_TOKENS = 2000

PUBMED_URL_TEMPLATE = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
