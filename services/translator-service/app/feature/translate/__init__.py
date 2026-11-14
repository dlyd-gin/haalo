import json
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ... import state
from ...config import SUPPORTED_LANGUAGES
from .model import TranslateRequest
from .stream import stream_translate_events

router = APIRouter()


@router.post("/translate")
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

    engine = state.get_engine()

    async def sse_stream() -> AsyncIterator[str]:
        async for event in stream_translate_events(
            engine, text, req.source_language, req.target_language
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(sse_stream(), media_type="text/event-stream")
