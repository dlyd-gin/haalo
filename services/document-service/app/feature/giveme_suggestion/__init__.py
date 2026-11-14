import asyncio
import json
import logging
import os
import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ...client import translator
from ...engine.docx_engine.highlight import docx_lines, highlight_docx, highlight_snippets
from ..common import DOCX_MIME, multipart_end, multipart_part

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/giveme-suggestion")
async def giveme_suggestion(file: UploadFile = File(...), instruction: str = Form(...)):
    """Streams multipart/mixed: first the highlighted docx, then a JSON summary of the highlights
    ({summary, highlights}, or {error, highlights} if the summary failed). Everything that can fail
    with a status code runs before streaming starts, so those errors stay plain JSON."""
    docx_bytes = await file.read()
    if not docx_bytes:
        raise HTTPException(400, "empty file")
    if not instruction.strip():
        raise HTTPException(400, "instruction must not be empty")
    try:
        lines = await asyncio.to_thread(docx_lines, docx_bytes)
    except Exception as exc:  # noqa: BLE001 - python-docx raises several types for a non-docx upload
        raise HTTPException(400, "invalid docx") from exc
    if not lines:
        raise HTTPException(400, "docx has no text")
    logger.debug("giveme-suggestion: %d lines", len(lines))

    suggestions = await translator.request_suggestions(instruction.strip(), lines)
    content = await asyncio.to_thread(highlight_docx, docx_bytes, suggestions)
    if content is None:  # no suggestions, or none that map onto the document
        raise HTTPException(404, "no suggestion found in document")
    filename = f"suggested-{os.path.basename(file.filename or 'document.docx')}"
    return suggestion_stream(instruction.strip(), highlight_snippets(lines, suggestions), content, DOCX_MIME, filename)


def suggestion_stream(instruction: str, highlights: list[str], content: bytes, mime: str, filename: str) -> StreamingResponse:
    """multipart/mixed: the highlighted file (`content`, as `mime`), then the JSON summary of
    `highlights` ({summary, highlights}, or {error, highlights} if the summary failed)."""
    boundary = uuid.uuid4().hex

    async def parts():
        # The file first: it is ready now, while the summary still needs an LLM call.
        yield multipart_part(
            boundary,
            {
                "Content-Type": mime,
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            },
            content,
        )
        try:
            summary = {"summary": await translator.request_summary(instruction, highlights)}
        except HTTPException as exc:  # the 200 status is already sent: report it inside the part
            logger.warning("giveme-suggestion: summary failed: %s", exc.detail)
            summary = {"error": exc.detail}
        summary["highlights"] = highlights
        yield multipart_part(boundary, {"Content-Type": "application/json"}, json.dumps(summary).encode())
        yield multipart_end(boundary)

    return StreamingResponse(parts(), media_type=f"multipart/mixed; boundary={boundary}")
