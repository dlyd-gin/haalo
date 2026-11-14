import io
import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from ...client import ocr, translator
from ...engine.docx_engine.highlight import highlight_snippets, valid_groundings
from ..common import upright
from ..giveme_suggestion import suggestion_stream

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/giveme-suggestion-image")
async def giveme_suggestion_image(file: UploadFile = File(...), instruction: str = Form(...)):
    """/giveme-suggestion straight on an image: ocr-service reads its lines, the instruction is
    grounded against them, and ocr-service highlights the grounded phrases on the image itself.
    Streams the highlighted PNG, then the JSON summary. 422 when no text is found."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if not instruction.strip():
        raise HTTPException(400, "instruction must not be empty")
    content_type = file.content_type
    if (turned := upright(data)) is not None:
        data, content_type = turned, "image/png"
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(400, "file is not a valid image") from exc

    lines = await ocr.request_ocr_lines(data, content_type)
    lines = [line for line in lines if line["text"].strip()]
    if not lines:
        raise HTTPException(422, "no text detected in image")
    texts = [line["text"] for line in lines]
    logger.debug("giveme-suggestion-image: %d lines", len(texts))

    suggestions = await translator.request_suggestions(instruction.strip(), texts)
    by_line = valid_groundings(suggestions, texts)
    if not by_line:  # no suggestions, or none that map onto the image's text
        raise HTTPException(404, "no suggestion found in document")
    phrases = [
        {"line_text": texts[index], "line_bbox": [round(v) for v in lines[index]["bbox"]], "start": start, "end": end}
        for index in sorted(by_line)
        for start, end in by_line[index]
    ]
    png = await ocr.request_highlight(data, content_type, phrases)
    stem = os.path.splitext(os.path.basename(file.filename or ""))[0] or "image"
    return suggestion_stream(
        instruction.strip(), highlight_snippets(texts, suggestions), png, "image/png", f"suggested-{stem}.png"
    )
