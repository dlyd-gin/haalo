import asyncio
import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...client import translator
from ...engine.docx_engine.highlight import docx_lines, highlight_docx
from ..common import docx_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ground-state")
async def ground_state(file: UploadFile = File(...), state: str = Form(...)):
    docx_bytes = await file.read()
    if not docx_bytes:
        raise HTTPException(400, "empty file")
    if not state.strip():
        raise HTTPException(400, "state must not be empty")
    try:
        lines = await asyncio.to_thread(docx_lines, docx_bytes)
    except Exception as exc:  # noqa: BLE001 - python-docx raises several types for a non-docx upload
        raise HTTPException(400, "invalid docx") from exc
    if not lines:
        raise HTTPException(400, "docx has no text")
    logger.debug("ground-state: %d lines", len(lines))

    groundings = await translator.request_groundings(state.strip(), lines)
    content = await asyncio.to_thread(highlight_docx, docx_bytes, groundings)
    if content is None:
        raise HTTPException(404, "state not found in document")

    return docx_response(content, f"grounded-{os.path.basename(file.filename or 'document.docx')}")
