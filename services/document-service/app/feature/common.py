import io
import os
import tempfile

import pdfplumber
from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError
from starlette.background import BackgroundTask

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upright(data: bytes) -> bytes | None:
    """The image as PNG turned the way its EXIF orientation says, or None if it needs no turn (or is
    not a readable image). ocr-service turns it the same way, so its boxes are in the turned image's
    pixels: the page, crops and highlights must use that image too."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.getexif().get(ExifTags.Base.Orientation, 1) in (0, 1):
                return None
            turned = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError, SyntaxError):
        return None
    if turned.mode not in ("1", "L", "LA", "I", "P", "RGB", "RGBA"):
        turned = turned.convert("RGB")  # e.g. a CMYK JPEG, which PNG can't hold
    out = io.BytesIO()
    turned.save(out, format="PNG")
    return out.getvalue()


def count_pages(pdf_bytes: bytes) -> int:
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return len(pdf.pages)
    except Exception as exc:  # noqa: BLE001 - any parse failure means an invalid/unsupported PDF
        raise HTTPException(status_code=400, detail="invalid PDF") from exc


def validate_images_request(pdf_bytes: bytes, batch_size: int) -> None:
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="pdf file must not be empty")
    if batch_size < 1:
        raise HTTPException(status_code=400, detail="batch_size must be at least 1")


def resolve_pages(pages: list[int] | None, page_count: int) -> list[int]:
    page_list = pages if pages is not None else list(range(1, page_count + 1))
    if any(not 1 <= p <= page_count for p in page_list):
        raise HTTPException(status_code=400, detail=f"page numbers must be between 1 and {page_count}")
    return page_list


def validate_page_request(pdf_bytes: bytes, x_tolerance_ratio: float | None, image_dpi: int | None) -> None:
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="pdf file must not be empty")
    if x_tolerance_ratio is not None and x_tolerance_ratio <= 0:
        raise HTTPException(status_code=400, detail="x_tolerance_ratio must be greater than 0")
    if image_dpi is not None and image_dpi < 1:
        raise HTTPException(status_code=400, detail="image_dpi must be at least 1")


def multipart_part(boundary: str, headers: dict[str, str], body: bytes) -> bytes:
    """One part of a multipart/mixed body, opening delimiter included; close the body with
    multipart_end(boundary)."""
    head = "".join(f"{name}: {value}\r\n" for name, value in headers.items())
    return f"--{boundary}\r\n{head}\r\n".encode() + body + b"\r\n"


def multipart_end(boundary: str) -> bytes:
    return f"--{boundary}--\r\n".encode()


def docx_response(content: bytes, filename: str) -> FileResponse:
    fd, path = tempfile.mkstemp(suffix=".docx")
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return FileResponse(
        path,
        media_type=DOCX_MIME,
        filename=filename,
        background=BackgroundTask(os.unlink, path),
    )
