import json
import time
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ... import state
from ...config import LANGUAGE_MAP
from .stream import stream_transcript_events

router = APIRouter()


@router.post("/transcribe")
async def transcribe(request: Request, language: str = Query(...)):
    audio_bytes = await request.body()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="audio body must not be empty")

    model_language = LANGUAGE_MAP.get(language)
    if model_language is None:
        raise HTTPException(status_code=400, detail=f"unsupported language: {language}")

    engine = state.get_engine()
    requested_at = time.monotonic()

    async def sse_stream() -> AsyncIterator[str]:
        # Held for the whole stream, not just a single call — same reasoning as
        # tts-service's state.engine_lock.
        async with state.engine_lock:
            queue_wait_s = time.monotonic() - requested_at
            async for event in stream_transcript_events(engine, audio_bytes, model_language):
                yield f"data: {json.dumps(event)}\n\n"
            print(
                f"[stt-service] transcribe stream done: queue_wait={queue_wait_s:.2f}s "
                f"total={time.monotonic() - requested_at:.2f}s bytes={len(audio_bytes)}"
            )

    return StreamingResponse(sse_stream(), media_type="text/event-stream")
