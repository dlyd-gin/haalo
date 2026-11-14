import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from ... import state
from ...config import CONTINUE_MAX, CONTINUE_MIN_RATIO
from ...engine.ocr_engine import OcrEngine
from ..common import crop_below, model_image_file, read_image
from .model import OcrLine

logger = logging.getLogger(__name__)

router = APIRouter()


def _analyze_blocking(engine: OcrEngine, data: bytes, suffix: str, width: int, height: int) -> list[dict]:
    """The model's lines for the whole image, plus up to CONTINUE_MAX more passes over the part below
    where it stopped: on a tall, dense image (a menu) the VLM can close its JSON a third of the way
    down. Each pass re-reads the last row, so cells the model skipped there are picked up too. No pass
    runs when the unread bottom is no taller than the last line, as on a single table row or cell."""
    total = 1 + CONTINUE_MAX
    with model_image_file(data, suffix, width, height) as tmp:
        lines = engine.analyze(tmp.name, width, height, part=f"part 1/{total}, focus x=0..{width} y=0..{height}")
    for n in range(2, total + 1):
        if not lines:
            break
        last = max(lines, key=lambda line: line["bbox"][3])
        bottom = last["bbox"][3]
        if height - bottom <= CONTINUE_MIN_RATIO * height:
            break
        if height - bottom <= last["bbox"][3] - last["bbox"][1]:
            break  # no room below for another line: a one-row crop (a table row or cell), nothing was cut off
        top = min(line["bbox"][1] for line in lines if line["bbox"][3] > last["bbox"][1])
        crop_height = height - top
        with model_image_file(crop_below(data, top), ".png", width, crop_height) as tmp:
            more = engine.analyze(
                tmp.name, width, crop_height, part=f"part {n}/{total}, focus x=0..{width} y={top}..{height}"
            )
        shifted = [
            {"text": line["text"], "bbox": [line["bbox"][0], line["bbox"][1] + top, line["bbox"][2], line["bbox"][3] + top]}
            for line in more
        ]
        added = [line for line in shifted if not any(_same_line(line, seen) for seen in lines)]
        lines += added
        logger.debug("analyze: part %d/%d, continued below y=%d: %d lines added", n, total, top, len(added))
        if not added or max(line["bbox"][3] for line in added) <= bottom:
            break
    return lines


def _same_line(a: dict, b: dict) -> bool:
    """Whether a re-read line is one already found: mostly the same box, or the same text on the same
    row (a price like "220" repeats down a menu, so text alone is not enough)."""
    ax1, ay1, ax2, ay2 = a["bbox"]
    bx1, by1, bx2, by2 = b["bbox"]
    if a["text"] == b["text"] and ay1 < by2 and by1 < ay2:
        return True
    inter = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return union > 0 and inter / union > 0.5


@router.post("/analyze", response_model=list[OcrLine])
async def analyze(request: Request):
    data = await request.body()
    data, width, height, suffix = read_image(data)

    engine = state.get_engine()

    try:
        return await asyncio.to_thread(_analyze_blocking, engine, data, suffix, width, height)
    except Exception as exc:  # noqa: BLE001 - surface any engine failure as a 500 body
        logger.exception("analyze: analyze failed")
        raise HTTPException(status_code=500, detail=f"analyze failed: {exc}") from exc
