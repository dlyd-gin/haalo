import base64
import io
import logging

import pdfplumber

from ...config import X_TOLERANCE_RATIO_FALLBACK
from .image import image_info, merge_bboxes, pad_bbox
from .layout import calibrate_x_tolerance_ratio, is_inside, join_line, layout_lines
from .table import detect_tables, leftover_lines, table_cells

logger = logging.getLogger(__name__)


def analyze_page(page: pdfplumber.page.Page) -> tuple[dict, list]:
    """The has_text/has_table/has_image flags /analyze reports for a page, plus the ruled tables
    behind has_table so callers can reuse them instead of detecting again."""
    ruled_tables = page.find_tables()
    flags = {"has_text": bool(page.chars), "has_table": bool(ruled_tables), "has_image": bool(page.images)}
    return flags, ruled_tables


def page_elements(
    pdf_page: pdfplumber.page.Page, x_tolerance_ratio: float | None, dpi: int
) -> tuple[list[dict], float] | None:
    """Text lines, tables and images of one page in source reading order (bbox top, then x0), as
    dicts {kind, bbox, markdown, ...}: "text" has text/words, "table" has table_markdown/cells and
    `leftovers` (lines of words inside the border but outside any cell, with the `above` flag for
    those written before the table), "image" has `n`, the cropped `png` bytes and a `data_uri`.
    Text lying inside a table or image bbox is not repeated. `markdown` is the element's rendering
    in the Markdown output. Returns (elements, x_tolerance_ratio used), or None when the page has
    neither a text layer nor images."""
    # The same page analysis /analyze reports decides which approaches run below.
    flags, ruled_tables = analyze_page(pdf_page)
    logger.debug("page elements: flags=%s", flags)
    image_boxes = [
        box
        for box in (
            pad_bbox(b, 0.0, pdf_page.bbox)
            for b in merge_bboxes([image_info(i, pdf_page.bbox)["bbox"] for i in pdf_page.images])
        )
        if box[2] > box[0] and box[3] > box[1]
    ] if flags["has_image"] else []
    if not flags["has_text"] and not image_boxes:
        return None
    ratio = (
        x_tolerance_ratio
        if x_tolerance_ratio is not None
        else calibrate_x_tolerance_ratio(pdf_page.chars, fallback=X_TOLERANCE_RATIO_FALLBACK)
        if flags["has_text"]
        else X_TOLERANCE_RATIO_FALLBACK
    )

    elements: list[dict] = []
    table_boxes = []
    for table, markdown, paragraphs in detect_tables(pdf_page, ratio, ruled_tables) if flags["has_table"] else []:
        box = list(table.bbox)
        words = pdf_page.filter(lambda o, b=box: is_inside(o, b)).extract_words(x_tolerance_ratio=ratio)
        above, below = leftover_lines(words, table.cells, table.rows[0].bbox if table.rows else table.bbox)
        content = "\n\n".join(
            t for t in ["\n".join(join_line(l) for l in above), markdown, *paragraphs, "\n".join(join_line(l) for l in below)] if t
        )
        elements.append(
            {
                "kind": "table",
                "bbox": box,
                "markdown": content,
                "table_markdown": markdown,
                "cells": table_cells(table, words),
                "grid_cells": [tuple(c) for c in table.cells],
                "leftovers": [(line, True) for line in above] + [(line, False) for line in below],
            }
        )
        table_boxes.append(box)

    for n, box in enumerate(image_boxes, 1):
        element = {"kind": "image", "bbox": box, "n": n}
        crop = pdf_page.crop(tuple(box)).to_image(resolution=dpi).original.convert("RGB")
        out = io.BytesIO()
        crop.save(out, format="PNG")
        element["png"] = out.getvalue()
        element["data_uri"] = "data:image/png;base64," + base64.b64encode(element["png"]).decode("ascii")
        element["markdown"] = (
            f"![<bbox[{', '.join(f'{v:.2f}' for v in box)}]>image {n}]({element['data_uri']})"
        )
        elements.append(element)

    if flags["has_text"]:
        excluded = table_boxes + image_boxes
        text_page = pdf_page.filter(lambda o: not any(is_inside(o, b) for b in excluded))
        for line in layout_lines(text_page, ratio, with_words=True):
            elements.append({"kind": "text", "bbox": line["bbox"], "markdown": line["text"], **line})

    elements.sort(key=lambda e: (e["bbox"][1], e["bbox"][0]))
    return elements, ratio


def assign_paragraphs(elements: list[dict]) -> None:
    """Set `paragraph` on each element: consecutive text lines with a small vertical gap share one
    id; every table and image is its own paragraph."""
    prev, pid = None, -1
    for e in elements:
        top, bottom = e["bbox"][1], e["bbox"][3]
        if not (prev and e["kind"] == "text" and prev["kind"] == "text" and top - prev["bbox"][3] <= (bottom - top) * 0.8):
            pid += 1
        e["paragraph"] = pid
        prev = e


def page_markdown(pdf_bytes: bytes, page: int, x_tolerance_ratio: float | None, dpi: int) -> str | None:
    """Stitch one 1-indexed page into a single Markdown document in source reading order: text
    lines, tables (GFM) and images (cropped, inlined as base64 PNG data URIs), all placed by their
    bbox (top, then x0). Text lying inside a table or image bbox is not repeated. Returns None when
    the page has neither a text layer nor images. Opens its own pdfplumber.PDF, so it is safe to
    run on a worker thread."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not 1 <= page <= len(pdf.pages):
                raise ValueError(f"page {page} out of range (1-{len(pdf.pages)})")
            result = page_elements(pdf.pages[page - 1], x_tolerance_ratio, dpi)
            if result is None:
                return None
            elements, _ = result
            assign_paragraphs(elements)
            parts: list[str] = []
            prev_pid = None
            for e in elements:
                if e["paragraph"] == prev_pid:
                    parts[-1] += "\n" + e["markdown"]
                else:
                    parts.append(e["markdown"])
                prev_pid = e["paragraph"]
            return "\n\n".join(parts)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - mirrors /analyze's parse-failure handling
        raise ValueError("invalid PDF") from exc
