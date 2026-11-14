import asyncio
import json
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import TypeAdapter, ValidationError

from ... import state
from ...config import HIGHLIGHT_COLOR, HIGHLIGHT_LOCATE
from ...engine.ocr_engine import OcrEngine
from ...engine.ocr_engine.boxes import resolve_boxes
from ...engine.ocr_engine.draw import draw_highlights
from ..common import model_image_file, read_image
from .model import Phrase

logger = logging.getLogger(__name__)

router = APIRouter()

_PHRASES = TypeAdapter(list[Phrase])


def _highlight_blocking(
    engine: OcrEngine | None, data: bytes, suffix: str, width: int, height: int, phrases: list[Phrase]
) -> tuple[bytes, list[dict]]:
    located: list[list[int] | None] = [None] * len(phrases)
    if engine is not None:
        with model_image_file(data, suffix, width, height) as tmp:
            located = engine.locate(tmp.name, width, height, [p.text for p in phrases])
    boxes = resolve_boxes([p.model_dump() for p in phrases], located)
    return draw_highlights(data, [b["bbox"] for b in boxes], HIGHLIGHT_COLOR), boxes


@router.post("/highlight")
async def highlight(file: UploadFile = File(...), phrases: str = Form(...)):
    """The image as PNG with each phrase highlighted. Each phrase is a [start, end) span of one OCR
    line (as /analyze returns it); the model is asked where each phrase is, and a phrase it misses
    or puts off its line is placed by its char position within the line bbox. The boxes used are in
    the X-Highlight-Boxes header ([{bbox, source: "located" | "estimated"}])."""
    data = await file.read()
    data, width, height, suffix = read_image(data)
    try:
        parsed = _PHRASES.validate_json(phrases)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid phrases: {exc.errors()[0]['msg']}") from exc
    if not parsed:
        raise HTTPException(status_code=400, detail="phrases must not be empty")

    engine = state.get_engine() if HIGHLIGHT_LOCATE else None

    try:
        png, boxes = await asyncio.to_thread(_highlight_blocking, engine, data, suffix, width, height, parsed)
    except Exception as exc:  # noqa: BLE001 - surface any engine failure as a 500 body
        logger.exception("highlight: highlight failed")
        raise HTTPException(status_code=500, detail=f"highlight failed: {exc}") from exc
    logger.debug("highlight: %s", boxes)
    return Response(png, media_type="image/png", headers={"X-Highlight-Boxes": json.dumps(boxes)})
