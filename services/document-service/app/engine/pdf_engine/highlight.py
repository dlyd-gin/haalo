import io

import pdfplumber
from pypdf import PdfWriter
from pypdf.annotations import Highlight
from pypdf.generic import ArrayObject, FloatObject

from ...config import PDF_HIGHLIGHT_COLOR, X_TOLERANCE_RATIO_FALLBACK
from ..docx_engine.highlight import valid_groundings
from .layout import calibrate_x_tolerance_ratio, group_lines, join_line_spans


def pdf_lines(pdf_bytes: bytes) -> list[dict]:
    """Every visual text line of the PDF, page by page in reading order, as {page (0-indexed),
    page_height (MediaBox height), text, words: [(start, end, word)]}: `text` is join_line's, and
    each word (a pdfplumber word with its `chars`) keeps its [start, end) offset into it. Index in
    this list == line number for grounding. Raises ValueError("invalid PDF") when it can't be
    parsed, and ValueError("unsupported PDF: ...") when it has no text layer or a rotated page
    (highlight coordinates assume an unrotated page) — callers fall back to the docx path."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            out = []
            for index, pdf_page in enumerate(pdf.pages):
                if pdf_page.rotation:
                    raise ValueError(f"unsupported PDF: page {index + 1} is rotated")
                ratio = calibrate_x_tolerance_ratio(pdf_page.chars, fallback=X_TOLERANCE_RATIO_FALLBACK)
                words = pdf_page.extract_words(x_tolerance_ratio=ratio, return_chars=True)
                page_height = pdf_page.mediabox[3] - pdf_page.mediabox[1]
                for line in group_lines(words):
                    text, spans = join_line_spans(line)
                    if text.strip():
                        out.append(
                            {
                                "page": index,
                                "page_height": page_height,
                                "text": text,
                                "words": [(start, end, word) for (start, end), word in zip(spans, line)],
                            }
                        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - mirrors /analyze's parse-failure handling
        raise ValueError("invalid PDF") from exc
    if not out:
        raise ValueError("unsupported PDF: no text layer")
    return out


def _span_boxes(words: list[tuple[int, int, dict]], start: int, end: int) -> list[tuple[float, float, float, float]]:
    """[x0, top, x1, bottom] of each word piece that [start, end) covers: the whole word's bbox, or
    the bbox of just its covered chars when the span cuts through it (whole word when its chars
    don't map 1:1 onto its text, e.g. ligatures)."""
    boxes = []
    for w_start, w_end, word in words:
        a, b = max(start, w_start) - w_start, min(end, w_end) - w_start
        if a >= b:
            continue
        chars = word.get("chars") or []
        pieces = chars[a:b] if (a, b) != (0, w_end - w_start) and len(chars) == w_end - w_start else [word]
        boxes.append(
            (
                min(p["x0"] for p in pieces),
                min(p["top"] for p in pieces),
                max(p["x1"] for p in pieces),
                max(p["bottom"] for p in pieces),
            )
        )
    return boxes


def _to_user_space(box: tuple[float, float, float, float], page_height: float) -> tuple[float, float, float, float]:
    """pdfplumber [x0, top, x1, bottom] -> PDF user space (x0, y0, x1, y1). pdfplumber keeps x in
    user space and measures top as page_height - y (MediaBox height, also when the MediaBox
    doesn't start at the origin), so y = page_height - top."""
    x0, top, x1, bottom = box
    return x0, page_height - bottom, x1, page_height - top


def highlight_pdf(pdf_bytes: bytes, lines: list[dict], groundings: list[dict]) -> bytes | None:
    """Add a /Highlight annotation per grounded [start, end) span of its line (one quad per word
    piece it covers), leaving the page content itself untouched. `lines` is pdf_lines' result for
    the same bytes. Returns None when no grounding is valid."""
    by_line = valid_groundings(groundings, [line["text"] for line in lines])
    if not by_line:
        return None

    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    added = 0
    for index, spans in sorted(by_line.items()):
        line = lines[index]
        for start, end in spans:
            rects = [_to_user_space(box, line["page_height"]) for box in _span_boxes(line["words"], start, end)]
            if not rects:  # the span only covers separators between words
                continue
            quads = [v for x0, y0, x1, y1 in rects for v in (x0, y1, x1, y1, x0, y0, x1, y0)]  # TL TR BL BR
            writer.add_annotation(
                page_number=line["page"],
                annotation=Highlight(
                    rect=(
                        min(r[0] for r in rects),
                        min(r[1] for r in rects),
                        max(r[2] for r in rects),
                        max(r[3] for r in rects),
                    ),
                    quad_points=ArrayObject([FloatObject(v) for v in quads]),
                    highlight_color=PDF_HIGHLIGHT_COLOR,
                    printing=True,
                ),
            )
            added += 1
    if not added:
        return None

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
