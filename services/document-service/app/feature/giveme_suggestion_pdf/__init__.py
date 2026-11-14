import asyncio
import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...client import translator
from ...engine.docx_engine.highlight import highlight_snippets
from ...engine.pdf_engine.highlight import highlight_pdf, pdf_lines
from ..giveme_suggestion import suggestion_stream

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/giveme-suggestion-pdf")
async def giveme_suggestion_pdf(file: UploadFile = File(...), instruction: str = Form(...)):
    """/giveme-suggestion straight on a PDF, without converting it to docx first: grounds the
    instruction against the PDF's own text lines and streams the original PDF with highlight
    annotations, then the JSON summary. 422 when the PDF has no usable text layer (scanned, or a
    rotated page) — the caller then falls back to /extract-words + /giveme-suggestion."""
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "empty file")
    if not instruction.strip():
        raise HTTPException(400, "instruction must not be empty")
    try:
        lines = await asyncio.to_thread(pdf_lines, pdf_bytes)
    except ValueError as exc:
        if str(exc).startswith("unsupported PDF"):
            logger.info("giveme-suggestion-pdf: %s", exc)
            raise HTTPException(422, "pdf has no usable text layer") from exc
        raise HTTPException(400, str(exc)) from exc
    texts = [line["text"] for line in lines]
    logger.debug("giveme-suggestion-pdf: %d lines", len(texts))

    suggestions = await translator.request_suggestions(instruction.strip(), texts)
    content = await asyncio.to_thread(highlight_pdf, pdf_bytes, lines, suggestions)
    if content is None:  # no suggestions, or none that map onto the document
        raise HTTPException(404, "no suggestion found in document")
    filename = f"suggested-{os.path.basename(file.filename or 'document.pdf')}"
    return suggestion_stream(
        instruction.strip(), highlight_snippets(texts, suggestions), content, "application/pdf", filename
    )
