import asyncio
import io
import logging

import pdfplumber
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ...config import BATCH_SIZE
from ...engine.pdf_engine.table import extract_page_tables

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/extract-tables")
async def extract_tables(
    file: UploadFile = File(...),
    pages: list[int] | None = Form(None),
    batch_size: int = Form(BATCH_SIZE),
    x_tolerance_ratio: float | None = Form(None),
):
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="pdf file must not be empty")
    if batch_size < 1:
        raise HTTPException(status_code=400, detail="batch_size must be at least 1")
    if x_tolerance_ratio is not None and x_tolerance_ratio <= 0:
        raise HTTPException(status_code=400, detail="x_tolerance_ratio must be greater than 0")

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
    except Exception as exc:  # noqa: BLE001 - any parse failure means an invalid/unsupported PDF
        raise HTTPException(status_code=400, detail="invalid PDF") from exc

    page_list = pages if pages is not None else list(range(1, page_count + 1))
    if any(not 1 <= p <= page_count for p in page_list):
        raise HTTPException(status_code=400, detail=f"page numbers must be between 1 and {page_count}")

    semaphore = asyncio.Semaphore(batch_size)

    async def _extract_one(page: int) -> dict | None:
        async with semaphore:
            result = await asyncio.to_thread(extract_page_tables, pdf_bytes, page, x_tolerance_ratio)
        return None if result is None else {"page": page, **result}

    results = [r for r in await asyncio.gather(*(_extract_one(p) for p in page_list)) if r is not None]
    logger.debug("extract-tables: %d of %d page(s) had a text layer", len(results), len(page_list))
    if not results:
        return Response(status_code=204)  # only scanned/image-only pages: nothing to extract
    return {"page_count": page_count, "pages": sorted(results, key=lambda r: r["page"])}
