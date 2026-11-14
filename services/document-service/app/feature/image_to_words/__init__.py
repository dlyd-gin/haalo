import asyncio
import io
import logging
import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from starlette.background import BackgroundTask

from ...client import ocr
from ...config import OCR_TABLE_CELLS_MAX, OCR_TABLE_ROWS_MAX
from ...engine.docx_engine.image_docx import image_docx
from ...engine.docx_engine.image_table import ImageLayout, read_layout
from ..common import DOCX_MIME, upright

logger = logging.getLogger(__name__)

router = APIRouter()


async def _ocr_or_none(png: bytes, what: str) -> list[dict] | None:
    try:
        return await ocr.request_ocr_lines(png, "image/png")
    except HTTPException as exc:
        logger.warning("image-to-words: ocr of %s failed: %s", what, exc.detail)
        return None


async def _read_tables(data: bytes, lines: list[dict]) -> ImageLayout | None:
    """Detect ruled tables and read each row with its own ocr call (the page call's boxes are too
    rough to tell cells apart, and it skips lines on dense pages). A row whose read doesn't give one
    line per inked cell has those cells read one by one. None if detection fails: the page lines
    are then pinned as frames, as without a table."""
    try:
        layout = await asyncio.to_thread(read_layout, data, lines)
    except Exception as exc:  # noqa: BLE001 - a detection bug must not cost the whole conversion
        logger.warning("image-to-words: table detection failed: %s", exc)
        return None
    logger.debug("image-to-words: %d tables, %d rows to read", len(layout.tables), len(layout.bands))
    cells_left = OCR_TABLE_CELLS_MAX
    for i, band in enumerate(layout.bands):
        band_lines = await _ocr_or_none(band.png, f"table row {i}") if i < OCR_TABLE_ROWS_MAX else None
        if layout.fill(band, band_lines or None) or i >= OCR_TABLE_ROWS_MAX:
            continue
        for cell in band.cells:
            if cell.inked and cells_left > 0:
                cells_left -= 1
                crop = layout.cell_band(cell)
                cell_lines = await _ocr_or_none(crop.png, f"a cell of table row {i}")
                if cell_lines:
                    layout.fill_cell(crop, cell_lines)
    return layout


@router.post("/image-to-words")
async def image_to_words(file: UploadFile = File(...)):
    """One image -> one Word (.docx) file: ocr-service reads the text line by line with bboxes and
    each line is pinned at its bbox on a page of the image's size; ruled tables become Word tables,
    each row read again on its own. Errors carry the reason:
    400 bad image, 422 no text found, 502 ocr-service failure, 500 docx could not be built."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="image file must not be empty")
    content_type = file.content_type
    if (turned := upright(data)) is not None:
        data, content_type = turned, "image/png"
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            width, height = image.size
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail="file is not a valid image") from exc

    lines = await ocr.request_ocr_lines(data, content_type)
    logger.debug("image-to-words: %d ocr lines", len(lines))
    layout = await _read_tables(data, lines)
    if layout is not None:
        lines, tables = layout.lines(), layout.tables
    else:
        tables = []
    try:
        content = await asyncio.to_thread(image_docx, lines, width, height, tables)
    except Exception as exc:  # noqa: BLE001 - report any build failure as the response reason
        logger.exception("image-to-words: could not build docx")
        raise HTTPException(status_code=500, detail=f"could not build docx: {exc}") from exc
    if content is None:
        raise HTTPException(status_code=422, detail="no text detected in image")

    fd, path = tempfile.mkstemp(suffix=".docx")
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    stem = os.path.splitext(os.path.basename(file.filename or ""))[0] or "image"
    return FileResponse(
        path,
        media_type=DOCX_MIME,
        filename=f"{stem}.docx",
        background=BackgroundTask(os.unlink, path),
    )
