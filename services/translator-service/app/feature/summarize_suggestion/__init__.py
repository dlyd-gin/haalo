import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ... import state
from .model import SummarizeRequest, SummarizeResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/summarize-suggestion", response_model=SummarizeResponse)
async def summarize_suggestion(req: SummarizeRequest):
    intent = req.intent.strip()
    if not intent:
        raise HTTPException(status_code=400, detail="intent must not be empty")
    highlights = [h.strip() for h in req.highlights if h.strip()]
    if not highlights:
        raise HTTPException(status_code=400, detail="highlights must not be empty")

    engine = state.get_summarize_suggestion_engine()

    logger.debug("summarize-suggestion: intent=%r, %d highlights", intent, len(highlights))
    try:
        summary = await asyncio.to_thread(engine.summarize, intent, highlights)
    except Exception as exc:  # noqa: BLE001 - surface any engine failure as a 500 body
        logger.exception("summarize-suggestion: summary failed")
        raise HTTPException(status_code=500, detail=f"summary failed: {exc}") from exc
    logger.debug("summarize-suggestion: %r", summary)
    return {"summary": summary}
