import time
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ... import state
from ...config import LANGUAGE_VOICE_MAP
from .stream import stream_wav_chunks

router = APIRouter()


@router.get("/synthesize")
async def synthesize(text: str = Query(...), language: str = Query(...)):
    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    voice = LANGUAGE_VOICE_MAP.get(language)
    if voice is None:
        raise HTTPException(status_code=400, detail=f"unsupported language: {language}")

    engine = state.get_engine()
    requested_at = time.monotonic()

    async def byte_stream() -> AsyncIterator[bytes]:
        # Held for the whole stream, not just a single call: the model's shared mutable
        # streaming-decoder state would race under concurrent requests otherwise.
        async with state.engine_lock:
            queue_wait_s = time.monotonic() - requested_at
            async for chunk in stream_wav_chunks(engine, text, voice):
                yield chunk
            print(
                f"[tts-service] synthesize stream done: queue_wait={queue_wait_s:.2f}s "
                f"total={time.monotonic() - requested_at:.2f}s chars={len(text)}"
            )

    return StreamingResponse(byte_stream(), media_type="audio/wav")
