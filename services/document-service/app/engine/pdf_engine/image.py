import io

import pdfplumber
from pdfminer.pdftypes import resolve1

from ...config import ANNOTATE_DPI

# PDF stream filter name (abbreviated inline-image names included) -> image type. Flate/LZW/
# RunLength are lossless pixel-data encodings with no image-format identity of their own.
_IMAGE_TYPE_BY_FILTER = {
    "DCTDecode": "jpeg",
    "DCT": "jpeg",
    "JPXDecode": "jpeg2000",
    "JBIG2Decode": "jbig2",
    "CCITTFaxDecode": "ccitt",
    "CCF": "ccitt",
}
_RAW_FILTERS = {"FlateDecode", "Fl", "LZWDecode", "LZW", "RunLengthDecode", "RL", "ASCII85Decode", "A85"}


def _name(obj) -> str | None:
    """Name of a PDF name object (PSLiteral), or None for anything else."""
    name = getattr(resolve1(obj), "name", None)
    return name if isinstance(name, str) else None


def image_type(stream) -> str:
    """Image type from the stream's last compression filter (the one that produces the final
    pixel/file data): jpeg, jpeg2000, jbig2, ccitt, or raw for lossless/unfiltered pixel data."""
    attrs = getattr(stream, "attrs", None) or {}
    filters = resolve1(attrs.get("Filter", attrs.get("F")))
    if not isinstance(filters, list):
        filters = [filters] if filters is not None else []
    names = [n for n in map(_name, filters) if n]
    # ASCII/Flate wrappers can sit in front of an image codec, so prefer any image-codec filter.
    for n in reversed(names):
        if n in _IMAGE_TYPE_BY_FILTER:
            return _IMAGE_TYPE_BY_FILTER[n]
    if not names or names[-1] in _RAW_FILTERS:
        return "raw"
    return names[-1].removesuffix("Decode").lower()


def image_info(img: dict, page_bbox: tuple[float, float, float, float]) -> dict:
    x0, top, x1, bottom = img["x0"], img["top"], img["x1"], img["bottom"]
    width_pt, height_pt = x1 - x0, bottom - top
    src_w, src_h = img.get("srcsize") or (None, None)
    dpi = (
        [round(src_w / (width_pt / 72), 2), round(src_h / (height_pt / 72), 2)]
        if src_w and src_h and width_pt > 0 and height_pt > 0
        else None
    )
    # Clamp to the page: an image can be placed partly (or wholly) off the page. The page bbox need
    # not start at (0, 0) (e.g. a CropBox offset from the MediaBox).
    px0, ptop, px1, pbottom = page_bbox
    visible_w = max(0.0, min(x1, px1) - max(x0, px0))
    visible_h = max(0.0, min(bottom, pbottom) - max(top, ptop))
    colorspace = img.get("colorspace")
    return {
        "bbox": [x0, top, x1, bottom],
        "type": image_type(img.get("stream")),
        "width_px": src_w,
        "height_px": src_h,
        "dpi": dpi,
        "page_coverage": round(visible_w * visible_h / ((px1 - px0) * (pbottom - ptop)), 4),
        "colorspace": _name(colorspace[0]) if colorspace else None,
    }


def extract_page_images(pdf_bytes: bytes, page: int) -> dict:
    """List the images on a single 1-indexed page (bbox, type, pixel size, effective dpi, share of
    the page covered, colorspace). Opens its own pdfplumber.PDF, like extract_page_text, so it is
    safe to run concurrently from multiple threads."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not 1 <= page <= len(pdf.pages):
                raise ValueError(f"page {page} out of range (1-{len(pdf.pages)})")
            pdf_page = pdf.pages[page - 1]
            return {"images": [image_info(img, pdf_page.bbox) for img in pdf_page.images]}
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - mirrors /analyze's parse-failure handling
        raise ValueError("invalid PDF") from exc


# Image fragments within this many points of each other count as one picture when annotating:
# some PDF exporters draw a single picture as many abutting strips/tiles, and outlining each
# fragment separately stacks into a solid block that hides the image.
_MERGE_TOLERANCE = 1.0


def merge_bboxes(bboxes: list[list[float]], tolerance: float = _MERGE_TOLERANCE) -> list[list[float]]:
    """Union boxes that overlap or lie within `tolerance` points of each other (transitively),
    returning the merged [x0, top, x1, bottom] boxes sorted by (top, x0). Quadratic, which is fine
    for the box counts a page realistically has."""
    boxes = [list(b) for b in bboxes]
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if (
                    a[0] - tolerance <= b[2]
                    and b[0] - tolerance <= a[2]
                    and a[1] - tolerance <= b[3]
                    and b[1] - tolerance <= a[3]
                ):
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[j]
                    merged = True
                    break
            if merged:
                break
    return sorted(boxes, key=lambda b: (b[1], b[0]))


def pad_bbox(bbox: list[float], margin: float, page_bbox: tuple[float, float, float, float]) -> list[float]:
    """Grow [x0, top, x1, bottom] by `margin` points on every side, clamped to `page_bbox` — the
    pdfplumber page's own bbox, which need not start at (0, 0), so the result is always croppable."""
    x0, top, x1, bottom = bbox
    px0, ptop, px1, pbottom = page_bbox
    return [
        max(px0, x0 - margin),
        max(ptop, top - margin),
        min(px1, x1 + margin),
        min(pbottom, bottom + margin),
    ]


def annotate_page_image(pdf_bytes: bytes, page: int, margin: float = 0.0) -> tuple[bytes, int]:
    """Render a single 1-indexed page to JPEG with a red rectangle around each image found by
    extract_page_images. Returns (jpeg_bytes, image_count). Opens its own pdfplumber.PDF, like the
    other per-page helpers, so it is safe to run on a worker thread."""
    images = extract_page_images(pdf_bytes, page)["images"]  # also range-checks the page
    merged = merge_bboxes([img["bbox"] for img in images])
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pdf_page = pdf.pages[page - 1]
            # Pad after merging so the margin never causes extra fragments to merge.
            boxes = [pad_bbox(b, margin, pdf_page.bbox) for b in merged]
            rendered = pdf_page.to_image(resolution=ANNOTATE_DPI)
            rendered.draw_rects(boxes, stroke="red", fill=None, stroke_width=2)
            out = io.BytesIO()
            rendered.annotated.convert("RGB").save(out, format="JPEG", quality=85)
            return out.getvalue(), len(boxes)
    except Exception as exc:  # noqa: BLE001 - mirrors /analyze's parse-failure handling
        raise ValueError("invalid PDF") from exc
