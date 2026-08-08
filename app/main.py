"""FastAPI app: SSE query endpoint + static frontend."""
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.rag import stream_answer  # noqa: E402  (import after load_dotenv)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Dermatology PubMed RAG")


def _sse(event: dict) -> str:
    """Format a dict as one SSE frame: named event + JSON data line."""
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@app.get("/api/query")
async def query(q: str = Query(..., min_length=1)):
    async def event_stream():
        async for event in stream_answer(q):
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
