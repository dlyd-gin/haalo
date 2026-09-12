import asyncio
import json
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import MODEL_PATH, SUPPORTED_LANGUAGES
from .translator_engine import TranslatorEngine

_engine: TranslatorEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    print(f"[translator-service] loading model from {MODEL_PATH} ...")
    _engine = TranslatorEngine(MODEL_PATH)
    print("[translator-service] model loaded")
    yield
    _engine = None


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


class TranslateRequest(BaseModel):
    text: str
    source_language: str
    target_language: str


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _engine is not None}


def _stream_translate_events(
    engine: TranslatorEngine, text: str, source_language: str, target_language: str
) -> AsyncIterator[dict[str, str]]:
    """Bridge the engine's blocking generator (MLX generation is CPU/GPU-bound) onto the
    event loop: a worker thread drives the generator and pushes events into an asyncio.Queue
    via call_soon_threadsafe, and this async generator just drains that queue."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def worker() -> None:
        try:
            for event in engine.translate_stream(text, source_language, target_language):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:  # noqa: BLE001 - relay any engine failure to the client
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        while True:
            event = await queue.get()
            if event is sentinel:
                break
            yield event

    return event_generator()


@app.post("/translate")
async def translate(req: TranslateRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    if req.source_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400, detail=f"unsupported source_language: {req.source_language}"
        )
    if req.target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400, detail=f"unsupported target_language: {req.target_language}"
        )

    if _engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")

    async def sse_stream() -> AsyncIterator[str]:
        async for event in _stream_translate_events(
            _engine, text, req.source_language, req.target_language
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")
