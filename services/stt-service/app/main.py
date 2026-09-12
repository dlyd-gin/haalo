import asyncio
import json
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import LANGUAGE_MAP, MODEL_PATH
from .stt_engine import SttEngine

_engine: SttEngine | None = None

# The shared model instance keeps mutable streaming-decoder state on itself, just like
# tts-service's TtsEngine — serialize concurrent requests against it.
_engine_lock = anyio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    print(f"[stt-service] loading model from {MODEL_PATH} ...")
    _engine = SttEngine(MODEL_PATH)
    print("[stt-service] model loaded")
    yield
    _engine = None


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _engine is not None}


def _bridge_transcript_events(
    engine: SttEngine, audio_bytes: bytes, language: str
) -> AsyncIterator[dict]:
    """Bridge the engine's blocking generator (mlx-audio decoding is CPU/GPU-bound) onto
    the event loop: a worker thread drives the generator and pushes events into an
    asyncio.Queue via call_soon_threadsafe, and this async generator just drains that
    queue. Mirrors translator-service's _stream_translate_events."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def worker() -> None:
        try:
            accumulated_text = ""
            language_detected = language
            for result in engine.transcribe_stream(audio_bytes, language):
                accumulated_text += result["text"]
                language_detected = result["language"] or language_detected
                if result["is_final"]:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "done", "text": accumulated_text, "language": language_detected},
                    )
                else:
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"type": "delta", "text": result["text"]}
                    )
        except Exception as exc:  # noqa: BLE001 - relay any engine failure to the client
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator() -> AsyncIterator[dict]:
        while True:
            event = await queue.get()
            if event is sentinel:
                break
            yield event

    return event_generator()


@app.post("/transcribe")
async def transcribe(request: Request, language: str = Query(...)):
    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio body must not be empty")

    model_language = LANGUAGE_MAP.get(language)
    if model_language is None:
        raise HTTPException(status_code=400, detail=f"unsupported language: {language}")

    if _engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")

    engine = _engine
    requested_at = time.monotonic()

    async def sse_stream() -> AsyncIterator[str]:
        # Held for the whole stream, not just a single call — same reasoning as
        # tts-service's _engine_lock.
        async with _engine_lock:
            queue_wait_s = time.monotonic() - requested_at
            async for event in _bridge_transcript_events(engine, audio_bytes, model_language):
                yield f"data: {json.dumps(event)}\n\n"
            print(
                f"[stt-service] transcribe stream done: queue_wait={queue_wait_s:.2f}s "
                f"total={time.monotonic() - requested_at:.2f}s bytes={len(audio_bytes)}"
            )

    return StreamingResponse(sse_stream(), media_type="text/event-stream")
