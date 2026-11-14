import asyncio
import logging

from fastapi import APIRouter, File, Form, UploadFile

from ...config import BATCH_SIZE
from ...engine.pdf_engine.image import extract_page_images
from ..common import count_pages, resolve_pages, validate_images_request

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/extract-images")
async def extract_images(
    file: UploadFile = File(...),
    pages: list[int] | None = Form(None),
    batch_size: int = Form(BATCH_SIZE),
):
    pdf_bytes = await file.read()
    validate_images_request(pdf_bytes, batch_size)
    page_count = count_pages(pdf_bytes)
    page_list = resolve_pages(pages, page_count)

    semaphore = asyncio.Semaphore(batch_size)

    async def _extract_one(page: int) -> dict:
        async with semaphore:
            result = await asyncio.to_thread(extract_page_images, pdf_bytes, page)
        return {"page": page, **result}

    results = await asyncio.gather(*(_extract_one(p) for p in page_list))
    logger.debug("extract-images: %d page(s) processed", len(results))
    return {"page_count": page_count, "pages": sorted(results, key=lambda r: r["page"])}
