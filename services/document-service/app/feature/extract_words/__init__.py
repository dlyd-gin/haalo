import asyncio
import logging
import os
import tempfile

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from ...config import ANNOTATE_DPI
from ...engine.docx_engine.page_docx import pages_docx
from ..common import DOCX_MIME, count_pages, resolve_pages, validate_page_request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/extract-words")
async def extract_words(
    file: UploadFile = File(...),
    page: int = Form(1),
    x_tolerance_ratio: float | None = Form(None),
    image_dpi: int | None = Form(None),
    all_pages: bool = Form(False),
):
    """One page (or, with all_pages, every page as its own Word section) -> one Word (.docx) file
    that keeps the PDF layout: text, tables and images are pinned at their bboxes on a page of the
    same size. Returns 204 when no requested page has a text layer or images."""
    pdf_bytes = await file.read()
    validate_page_request(pdf_bytes, x_tolerance_ratio, image_dpi)
    page_count = count_pages(pdf_bytes)
    pages = resolve_pages(None if all_pages else [page], page_count)

    content = await asyncio.to_thread(pages_docx, pdf_bytes, pages, x_tolerance_ratio, image_dpi or ANNOTATE_DPI)
    if content is None:
        return Response(status_code=204)
    if all_pages:
        stem = os.path.splitext(os.path.basename(file.filename or ""))[0] or "document"
        filename = f"{stem}.docx"
    else:
        filename = f"page-{page}.docx"

    fd, path = tempfile.mkstemp(suffix=".docx")
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    logger.debug("extract-words: pages %s, %d bytes", pages, len(content))
    return FileResponse(
        path,
        media_type=DOCX_MIME,
        filename=filename,
        background=BackgroundTask(os.unlink, path),
    )
