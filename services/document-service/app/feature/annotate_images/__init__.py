import asyncio
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ...config import BATCH_SIZE
from ...engine.pdf_engine.image import annotate_page_image
from ..common import count_pages, resolve_pages, validate_images_request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/annotate-images")
async def annotate_images(
    file: UploadFile = File(...),
    pages: list[int] | None = Form(None),
    batch_size: int = Form(BATCH_SIZE),
    margin: float = Form(0.0),
):
    """Same payload as /extract-images (plus an optional `margin`, in points, that pads each box
    outward), but returns one page as a JPEG with its images boxed. Exactly one page is rendered:
    `pages` omitted means page 1."""
    pdf_bytes = await file.read()
    validate_images_request(pdf_bytes, batch_size)
    if margin < 0:
        raise HTTPException(status_code=400, detail="margin must not be negative")
    page_count = count_pages(pdf_bytes)
    if pages is not None and len(pages) != 1:
        raise HTTPException(status_code=400, detail="annotate-images renders one page at a time; pass a single page")
    (page,) = resolve_pages(pages if pages is not None else [1], page_count)

    jpeg, image_count = await asyncio.to_thread(annotate_page_image, pdf_bytes, page, margin)
    logger.debug("annotate-images: page %d, %d image(s) boxed", page, image_count)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f'inline; filename="page-{page}-annotated.jpg"',
            "X-Image-Count": str(image_count),
        },
    )
