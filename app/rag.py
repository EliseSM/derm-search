"""Retrieval + Claude generation with native citations.

`stream_answer(query)` is an async generator that yields typed step events so the
FastAPI layer can forward them straight to the browser as SSE:

    {"type": "embedding"}                      # embedding the query locally
    {"type": "searching"}                      # querying the vector store
    {"type": "retrieved", "docs": [...]}       # top-k abstracts (title, pmid, url, score)
    {"type": "generating"}                     # calling Claude
    {"type": "token", "text": "..."}           # streamed answer text
    {"type": "citation", "index": N, ...}      # a source citation as it arrives
    {"type": "done"}
    {"type": "error", "message": "..."}
"""
import asyncio

from anthropic import AsyncAnthropic

from app.config import (
    CHROMA_DIR,
    CLAUDE_MODEL,
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    MAX_TOKENS,
    TOP_K,
)

SYSTEM_PROMPT = (
    "You are a dermatology research assistant. Answer the user's question using "
    "ONLY the provided PubMed abstracts. Cite the specific abstract(s) that support "
    "each claim. If the abstracts do not contain enough information to answer, say so "
    "plainly rather than guessing. Keep the answer concise and clinically clear."
)

# Lazily-loaded singletons (heavy to construct; reused across requests).
_model = None
_collection = None
_anthropic = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_collection():
    global _collection
    if _collection is None:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = AsyncAnthropic()
    return _anthropic


def _retrieve(query: str, k: int) -> list[dict]:
    """Blocking: embed the query and search Chroma. Run in a thread."""
    embedding = _get_model().encode(query, convert_to_numpy=True).tolist()
    result = _get_collection().query(
        query_embeddings=[embedding],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    docs = []
    for doc, meta, dist in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        docs.append({
            "abstract": doc,
            "title": meta["title"],
            "pmid": meta["pmid"],
            "url": meta["url"],
            "journal": meta.get("journal", ""),
            "year": meta.get("year", ""),
            # cosine distance -> rough similarity for display
            "score": round(1.0 - float(dist), 3),
        })
    return docs


def _build_content(query: str, docs: list[dict]) -> list[dict]:
    content = [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain",
                       "data": doc["abstract"]},
            "title": doc["title"] or f"PMID {doc['pmid']}",
            "citations": {"enabled": True},
        }
        for doc in docs
    ]
    content.append({"type": "text", "text": f"Question: {query}"})
    return content


async def stream_answer(query: str):
    try:
        yield {"type": "embedding"}
        yield {"type": "searching"}
        docs = await asyncio.to_thread(_retrieve, query, TOP_K)

        yield {
            "type": "retrieved",
            "docs": [
                {"title": d["title"], "pmid": d["pmid"], "url": d["url"],
                 "journal": d["journal"], "year": d["year"], "score": d["score"]}
                for d in docs
            ],
        }

        if not docs:
            yield {"type": "token",
                   "text": "No indexed abstracts were found. Did you build the index?"}
            yield {"type": "done"}
            return

        yield {"type": "generating"}
        client = _get_anthropic()
        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_content(query, docs)}],
        ) as stream:
            async for event in stream:
                if event.type != "content_block_delta":
                    continue
                delta = event.delta
                if delta.type == "text_delta":
                    yield {"type": "token", "text": delta.text}
                elif delta.type == "citations_delta":
                    cit = delta.citation
                    idx = getattr(cit, "document_index", None)
                    source = docs[idx] if idx is not None and idx < len(docs) else {}
                    yield {
                        "type": "citation",
                        "index": idx,
                        "cited_text": getattr(cit, "cited_text", ""),
                        "title": source.get("title", getattr(cit, "document_title", "")),
                        "pmid": source.get("pmid", ""),
                        "url": source.get("url", ""),
                    }

        yield {"type": "done"}
    except Exception as exc:  # surface failures to the UI instead of hanging
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
