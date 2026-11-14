import asyncio
import io

import pdfplumber

from ...config import X_TOLERANCE_RATIO_FALLBACK
from .layout import calibrate_x_tolerance_ratio, layout_lines


def extract_page_text(pdf_bytes: bytes, page: int, x_tolerance_ratio: float | None = None) -> dict:
    """Extract the text of a single 1-indexed page. Opens its own pdfplumber.PDF over an
    independent BytesIO view of pdf_bytes (rather than reusing a shared one) so this is safe to
    call concurrently from multiple threads, e.g. as a worker in extract_pages_batched.

    x_tolerance_ratio: None (default) auto-calibrates the word-gap threshold from this page's own
    characters via calibrate_x_tolerance_ratio; an explicit value always overrides calibration."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not 1 <= page <= len(pdf.pages):
                raise ValueError(f"page {page} out of range (1-{len(pdf.pages)})")
            pdf_page = pdf.pages[page - 1]
            ratio = (
                x_tolerance_ratio
                if x_tolerance_ratio is not None
                else calibrate_x_tolerance_ratio(pdf_page.chars, fallback=X_TOLERANCE_RATIO_FALLBACK)
            )
            lines = layout_lines(pdf_page, ratio)
            bbox = (
                [
                    min(l["bbox"][0] for l in lines),
                    min(l["bbox"][1] for l in lines),
                    max(l["bbox"][2] for l in lines),
                    max(l["bbox"][3] for l in lines),
                ]
                if lines
                else None
            )
            return {
                "text": "\n".join(l["text"] for l in lines),
                "bbox": bbox,
                "lines": lines,
                "x_tolerance_ratio": ratio,
            }
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - mirrors /analyze's parse-failure handling
        raise ValueError("invalid PDF") from exc


async def extract_pages_batched(
    pdf_bytes: bytes, pages: list[int], batch_size: int, x_tolerance_ratio: float | None = None
) -> list[dict]:
    """Extract text for each page in pages, running up to batch_size pages concurrently (each on
    its own thread with its own pdfplumber.PDF instance). Bounding concurrency this way also
    bounds peak memory to roughly batch_size pages' worth of parsed PDF structure at a time,
    instead of parsing/holding the whole document at once."""
    semaphore = asyncio.Semaphore(batch_size)

    async def _extract_one(page: int) -> dict:
        async with semaphore:
            result = await asyncio.to_thread(extract_page_text, pdf_bytes, page, x_tolerance_ratio)
        return {"page": page, **result}

    return await asyncio.gather(*(_extract_one(p) for p in pages))
