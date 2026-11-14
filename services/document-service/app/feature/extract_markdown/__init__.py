import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from ...config import ANNOTATE_DPI
from ...engine.pdf_engine.elements import page_markdown
from ..common import count_pages, resolve_pages, validate_page_request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/extract-markdown")
async def extract_markdown(
    file: UploadFile = File(...),
    page: int = Form(1),
    x_tolerance_ratio: float | None = Form(None),
    image_dpi: int | None = Form(None),
):
    """One page -> one Markdown file (text, tables and images stitched in source order, images
    embedded as base64 PNG). Returns 204 for a page with neither a text layer nor images."""
    pdf_bytes = await file.read()
    validate_page_request(pdf_bytes, x_tolerance_ratio, image_dpi)
    (page,) = resolve_pages([page], count_pages(pdf_bytes))

    markdown = await asyncio.to_thread(page_markdown, pdf_bytes, page, x_tolerance_ratio, image_dpi or ANNOTATE_DPI)
    if markdown is None:
        return Response(status_code=204)

    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(markdown + "\n")
    logger.debug("extract-markdown: page %d, %d chars", page, len(markdown))
    return FileResponse(
        path,
        media_type="text/markdown",
        filename=f"page-{page}.md",
        background=BackgroundTask(os.unlink, path),
    )
