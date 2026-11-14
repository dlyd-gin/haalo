import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ... import state
from .model import GivemeRequest, GivemeResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/giveme-suggestion", response_model=GivemeResponse, response_model_exclude_none=True)
async def giveme_suggestion(req: GivemeRequest):
    intent = req.intent.strip()
    if not intent:
        raise HTTPException(status_code=400, detail="intent must not be empty")
    if not any(line.strip() for line in req.context):
        raise HTTPException(status_code=400, detail="context must not be empty")

    ground_engine = state.get_giveme_suggestion_engine()

    logger.debug(
        "giveme-suggestion: intent=%r, %d context lines, include_reason=%s",
        intent, len(req.context), req.include_reason,
    )
    try:
        suggestions = await asyncio.to_thread(
            ground_engine.suggest, intent, req.context, req.include_reason
        )
    except Exception as exc:  # noqa: BLE001 - surface any engine failure as a 500 body
        logger.exception("giveme-suggestion: suggestion failed")
        raise HTTPException(status_code=500, detail=f"suggestion failed: {exc}") from exc
    logger.debug("giveme-suggestion: %d suggestions: %s", len(suggestions), suggestions)
    return {"suggestions": suggestions}
