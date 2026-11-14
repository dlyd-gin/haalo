import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ... import state
from .model import GroundRequest, GroundResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ground-state", response_model=GroundResponse)
async def ground_state(req: GroundRequest):
    text = req.state.strip()
    if not text:
        raise HTTPException(status_code=400, detail="state must not be empty")
    if not any(line.strip() for line in req.context):
        raise HTTPException(status_code=400, detail="context must not be empty")

    ground_engine = state.get_ground_state_engine()

    logger.debug("ground-state: state=%r, %d context lines", text, len(req.context))
    try:
        groundings = await asyncio.to_thread(ground_engine.ground, text, req.context)
    except Exception as exc:  # noqa: BLE001 - surface any engine failure as a 500 body
        logger.exception("ground-state: grounding failed")
        raise HTTPException(status_code=500, detail=f"grounding failed: {exc}") from exc
    logger.debug("ground-state: %d groundings: %s", len(groundings), groundings)
    return {"groundings": groundings}
