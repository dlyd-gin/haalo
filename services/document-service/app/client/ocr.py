import json
import logging

import httpx
from fastapi import HTTPException

from ..config import OCR_TIMEOUT, OCR_URL

logger = logging.getLogger(__name__)


async def request_ocr_lines(data: bytes, content_type: str | None) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=OCR_TIMEOUT) as client:
            response = await client.post(
                f"{OCR_URL}/analyze", content=data, headers={"Content-Type": content_type or "application/octet-stream"}
            )
    except httpx.HTTPError as exc:
        logger.warning("image-to-words: ocr unreachable: %s", exc)
        raise HTTPException(502, "ocr service unavailable") from exc
    _raise_for_status(response, "analyze")
    try:
        lines = response.json()
        if not isinstance(lines, list):
            raise TypeError("expected a list")
        return [
            {"text": str(line["text"]), "bbox": [float(v) for v in line["bbox"][:4]]}
            for line in lines
            if len(line["bbox"]) == 4
        ]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "ocr service returned an invalid response") from exc


async def request_highlight(data: bytes, content_type: str | None, phrases: list[dict]) -> bytes:
    """ocr-service /highlight: the image as PNG with each phrase ({line_text, line_bbox, start, end})
    highlighted. Same error mapping as request_ocr_lines."""
    try:
        async with httpx.AsyncClient(timeout=OCR_TIMEOUT) as client:
            response = await client.post(
                f"{OCR_URL}/highlight",
                files={"file": ("image", data, content_type or "application/octet-stream")},
                data={"phrases": json.dumps(phrases)},
            )
    except httpx.HTTPError as exc:
        logger.warning("highlight: ocr unreachable: %s", exc)
        raise HTTPException(502, "ocr service unavailable") from exc
    _raise_for_status(response, "highlight")
    logger.debug("highlight: boxes %s", response.headers.get("x-highlight-boxes"))
    return response.content


def _raise_for_status(response: httpx.Response, what: str) -> None:
    """ocr-service's 400 (bad image/input) stays 400 with its reason; anything else non-200 is a 502."""
    if response.status_code == 200:
        return
    logger.warning("%s: ocr returned %d: %s", what, response.status_code, response.text[:500])
    try:
        reason = response.json()["error"]
    except (ValueError, KeyError, TypeError):
        reason = f"ocr service error ({response.status_code})"
    raise HTTPException(400 if response.status_code == 400 else 502, reason)
