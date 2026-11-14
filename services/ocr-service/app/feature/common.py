import io
import tempfile

from fastapi import HTTPException
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from ..config import MAX_IMAGE_BYTES, MIN_LONG_SIDE


def read_image(data: bytes) -> tuple[bytes, int, int, str]:
    """(data, width, height, ".<format>") of an image body, turned upright first when its EXIF says
    so (then as PNG), or a 400 for an empty, oversized or non-image one."""
    if not data:
        raise HTTPException(status_code=400, detail="image body must not be empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail=f"image exceeds {MAX_IMAGE_BYTES} bytes")
    data = upright(data) or data
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            width, height = image.size
            fmt = (image.format or "PNG").lower()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail="body is not a valid image") from exc
    return data, width, height, f".{fmt}"


def upright(data: bytes) -> bytes | None:
    """The image as PNG turned the way its EXIF orientation says, or None if it needs no turn (or is
    not a readable image). mlx-vlm turns the image it loads, so a phone photo taken in portrait would
    otherwise get boxes normalized to the turned image but scaled by the raw width and height."""
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


def upscaled(data: bytes, width: int, height: int) -> bytes | None:
    """The image as PNG with its long side raised to MIN_LONG_SIDE, or None if it is big enough. A
    small, dense image (a phone photo of a menu, a table-row crop) gives the VLM too few vision tokens
    per glyph and it starts skipping lines. Boxes are normalized, so they still map to the original."""
    scale = MIN_LONG_SIDE / max(width, height)
    if scale <= 1:
        return None
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB").resize((round(width * scale), round(height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def crop_below(data: bytes, top: int) -> bytes:
    """The image as PNG from pixel row `top` down to its bottom, full width."""
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB").crop((0, top, image.width, image.height))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def model_image_file(data: bytes, suffix: str, width: int, height: int):
    """A named temp file holding the image as the model should see it (upscaled when small); use as
    a context manager. mlx-vlm takes an image path/URL, so the bytes are spilled to disk."""
    larger = upscaled(data, width, height)
    if larger is not None:
        data, suffix = larger, ".png"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix)
    tmp.write(data)
    tmp.flush()
    return tmp
