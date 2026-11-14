import io
import logging

import pdfplumber
from fastapi import APIRouter, HTTPException, Request

from ...engine.pdf_engine.elements import analyze_page
from ...engine.pdf_engine.layout import find_footer_words, find_header_words
from ...engine.pdf_engine.page_number import select_printed_page

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/analyze")
async def analyze(request: Request):
    pdf_bytes = await request.body()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="pdf body must not be empty")

    logger.debug("analyze: received %d bytes", len(pdf_bytes))

    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
    except Exception as exc:  # noqa: BLE001 - any parse failure means an invalid/unsupported PDF
        raise HTTPException(status_code=400, detail="invalid PDF") from exc

    with pdf:
        pages = []
        for index, page in enumerate(pdf.pages, start=1):
            footer_words = find_footer_words(page)
            header_words = find_header_words(page)

            logger.debug("page %d: header band has %d word(s), footer band has %d word(s)", index, len(header_words), len(footer_words))

            # Header wins over footer when both have a page-number candidate.
            printed_page = select_printed_page(
                header_words, page.width, prefer_bottom=False, band=f"page {index} header"
            ) or select_printed_page(
                footer_words, page.width, prefer_bottom=True, band=f"page {index} footer"
            )

            flags, _ = analyze_page(page)
            page_result = {
                "page": index,
                **flags,
                "has_header": bool(header_words),
                "has_footer": bool(footer_words),
                "printed_page": printed_page,
            }
            logger.debug("analyze: page %d -> %s", index, page_result)
            pages.append(page_result)

    logger.debug("analyze: %d page(s) processed", len(pages))
    return {"page_count": len(pages), "pages": pages}
