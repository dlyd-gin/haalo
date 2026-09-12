import asyncio
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anyio
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from .config import LANGUAGE_VOICE_MAP, MODEL_PATH
from .tts_engine import TtsEngine

_engine: TtsEngine | None = None

# The shared model instance keeps mutable streaming-decoder state on itself
# (reset at the start of every generate() call). run_in_threadpool dispatches
# onto a real multi-threaded executor, so without this lock two overlapping
# requests can race on that shared state and corrupt each other's output.
_engine_lock = anyio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    print(f"[tts-service] loading model from {MODEL_PATH} ...")
    _engine = TtsEngine(MODEL_PATH)
    print("[tts-service] model loaded")
    yield
    _engine = None


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _engine is not None}


def _bridge_byte_stream(engine: TtsEngine, text: str, voice: str) -> AsyncIterator[bytes]:
    """Bridge the engine's blocking generator (mlx-audio generation is CPU/GPU-bound) onto
    the event loop: a worker thread drives the generator and pushes chunks into an
    asyncio.Queue via call_soon_threadsafe, and this async generator just drains that queue.
    A failure mid-stream is logged and simply ends the stream early (no JSON error envelope
    is possible on a raw audio/wav body) — the client sees a truncated download."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def worker() -> None:
        try:
            for chunk in engine.synthesize_wav_stream(text, voice):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception as exc:  # noqa: BLE001 - can't relay this into an audio/wav body
            print(f"[tts-service] streaming synthesis failed: {exc}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def iterator() -> AsyncIterator[bytes]:
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield item

    return iterator()


@app.get("/synthesize")
async def synthesize(text: str = Query(...), language: str = Query(...)):
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    voice = LANGUAGE_VOICE_MAP.get(language)
    if voice is None:
        raise HTTPException(status_code=400, detail=f"unsupported language: {language}")

    if _engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")

    engine = _engine
    requested_at = time.monotonic()

    async def byte_stream() -> AsyncIterator[bytes]:
        # Held for the whole stream, not just a single call: the model's shared mutable
        # streaming-decoder state would race under concurrent requests otherwise.
        async with _engine_lock:
            queue_wait_s = time.monotonic() - requested_at
            async for chunk in _bridge_byte_stream(engine, text, voice):
                yield chunk
            print(
                f"[tts-service] synthesize stream done: queue_wait={queue_wait_s:.2f}s "
                f"total={time.monotonic() - requested_at:.2f}s chars={len(text)}"
            )

    return StreamingResponse(byte_stream(), media_type="audio/wav")
