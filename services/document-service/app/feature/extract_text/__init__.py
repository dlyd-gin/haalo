import io
import logging

import pdfplumber
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...config import BATCH_SIZE
from ...engine.pdf_engine.text import extract_pages_batched

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/extract-text")
async def extract_text(
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

    logger.debug(
        "extract-text: received %d bytes, pages=%s, batch_size=%d, x_tolerance_ratio=%s",
        len(pdf_bytes),
        pages,
        batch_size,
        x_tolerance_ratio,
    )

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
    except Exception as exc:  # noqa: BLE001 - any parse failure means an invalid/unsupported PDF
        raise HTTPException(status_code=400, detail="invalid PDF") from exc

    page_list = pages if pages is not None else list(range(1, page_count + 1))
    if any(not 1 <= p <= page_count for p in page_list):
        raise HTTPException(status_code=400, detail=f"page numbers must be between 1 and {page_count}")

    results = await extract_pages_batched(pdf_bytes, page_list, batch_size, x_tolerance_ratio)
    logger.debug("extract-text: %d page(s) extracted", len(results))
    return {"page_count": page_count, "pages": sorted(results, key=lambda r: r["page"])}
