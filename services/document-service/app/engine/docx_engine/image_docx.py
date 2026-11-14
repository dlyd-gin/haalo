import io
import re
import unicodedata
from statistics import median

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Pt

from .ooxml import run_xml, table_xml, tw

_PX_TO_PT = 0.75  # image pixels -> Word points, assuming 96 dpi
_MAX_PAGE_PT = 1584.0  # Word's maximum page side (22 inches)
_MIN_LINE_PX = 2  # an OCR line shorter than this has no usable bbox (the VLM sometimes collapses y1 == y2)
_FALLBACK_LINE_PX = 16  # stacked line height when no OCR line has a usable bbox


_LINE_SPACING = 1.2  # line pitch as a multiple of the font size
_MIN_FONT_PT = 6.0
_NEIGHBOR_GAP = 2.0  # points kept between a text box and the start of the text to its right
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _char_em(ch: str) -> float:
    """Rough advance width of one glyph in em, enough to predict wrapping: Arial-like for Latin text,
    a full em for wide glyphs (CJK ideographs, kana, hangul, full-width forms)."""
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    if ch == " ":
        return 0.28
    if ch in "il.,;:'|!":
        return 0.28
    if ch in "mwMW":
        return 0.85
    if ch.isupper():
        return 0.68
    if ch.isdigit():
        return 0.56
    return 0.52


def _text_width(text: str, size: float) -> float:
    return sum(_char_em(c) for c in text) * size


def _wrap_count(text: str, size: float, width: float) -> int:
    """Lines needed to wrap text greedily into width at the given font size."""
    count, used, space = 1, 0.0, _char_em(" ") * size
    for word in text.split():
        w = _text_width(word, size)
        if used and used + space + w > width:
            count, used = count + 1, w
        else:
            used += (space if used else 0.0) + w
        while used > width > 0 and w > width:  # a single word longer than the line breaks mid-word
            count, used, w = count + 1, used - width, w - width
    return count


def _fit_font(text: str, width: float, height: float) -> tuple[float, int]:
    """Largest font size (pt) at which text wrapped into width fits in height, and its line count.
    Falls back to the minimum size, with however many lines that needs."""
    size = max(min(height * 0.85, 48.0), _MIN_FONT_PT)
    size = round(size * 2) / 2
    while size > _MIN_FONT_PT:
        lines = _wrap_count(text, size, width)
        if lines * size * _LINE_SPACING <= height + 0.5:
            return size, lines
        size -= 0.5
    return _MIN_FONT_PT, _wrap_count(text, _MIN_FONT_PT, width)


def _fit_boxes(boxes: list[tuple[str, list[float]]], page_w: float) -> list[tuple[str, float, float, float, float, float]]:
    """Turn (text, bbox pt) into (text, font size, x, y, w, h) so frames neither wrap into each other nor
    run into the text on their right: the width is limited to the next box on the same row, the font
    is fitted to that width and the bbox height, and any remaining vertical collision is pushed down."""
    plain = [_BOLD_RE.sub(r"\1", t).replace("**", "") for t, _ in boxes]
    out = []
    for i, (_, (x0, y0, x1, y1)) in enumerate(boxes):
        h = y1 - y0
        limit = page_w
        for j, (_, (a0, b0, _a1, b1)) in enumerate(boxes):
            overlap = min(y1, b1) - max(y0, b0)
            if j != i and a0 > x0 + 1 and overlap > 0.5 * min(h, b1 - b0):
                limit = min(limit, a0 - _NEIGHBOR_GAP)
        avail = max(limit - x0, 1.0)
        size, lines = _fit_font(plain[i], min(max(x1 - x0, 1.0) * 1.05, avail), h)
        w = min(x1 - x0 + size, avail)  # slack for a wider substitute font, never into the right neighbour
        out.append([boxes[i][0], size, x0, y0, w, max(h, lines * size * _LINE_SPACING)])
    placed: list[list] = []
    for item in sorted(out, key=lambda o: (o[3], o[2])):
        for prev in placed:
            if item[2] < prev[2] + prev[4] and prev[2] < item[2] + item[4] and item[3] < prev[3] + prev[5] - 0.5 and item[3] > prev[3]:
                item[3] = prev[3] + prev[5]
        placed.append(item)
    return [tuple(o) for o in placed]


def _image_frame_xml(text: str, size: float, x: float, y: float, w: float, h: float) -> str:
    """One OCR paragraph as a page-pinned frame; **bold** markdown becomes bold runs and wrapped
    lines keep the font's own line pitch inside the frame."""
    runs, pos = [], 0
    for m in _BOLD_RE.finditer(text):
        runs.append((text[pos : m.start()], False))
        runs.append((m.group(1), True))
        pos = m.end()
    runs.append((text[pos:], False))
    body = "".join(run_xml(t.replace("**", ""), (size, "Arial", bold, False)) for t, bold in runs if t)
    return (
        f'<w:p {nsdecls("w")}><w:pPr>'
        f'<w:framePr w:w="{tw(w)}" w:h="{tw(h)}" w:hRule="exact" w:hSpace="0" '
        f'w:vSpace="0" w:wrap="around" w:vAnchor="page" w:hAnchor="page" w:x="{tw(x)}" w:y="{tw(y)}"/>'
        f'<w:spacing w:before="0" w:after="0" w:line="{tw(size * _LINE_SPACING)}" w:lineRule="exact"/></w:pPr>'
        + body
        + "</w:p>"
    )


_EDGE_PX = 2  # a box ending this close to the image bottom is "at the edge"
_SQUASHED_RATIO = 0.6  # an edge box shorter than this fraction of a typical line was clamped by the model
_ROW_GAP = 0.5  # gap between rebuilt rows, as a fraction of the line height
_PRICE_RE = re.compile(r"\+?\d+(?:[.,]\d+)?|V|VG|GF|DF|VEG")


def _rebuild_rows(lines: list[dict], placed: list[list[float]]) -> list[tuple[str, list[float]]]:
    """Positions for lines the model gave no usable y for (collapsed or clamped to the image edge).
    They continue below the placed lines in OCR order, keeping their own x and width. A line that is
    only a price / tag, or that starts right of the previous label's end, shares that label's row;
    anything else starts a new row, as tall as the label's wrapped text needs."""
    heights = sorted(b[3] - b[1] for b in placed if b[3] - b[1] >= _MIN_LINE_PX)
    line_h = median(heights[: max(len(heights) // 2, 1)]) if heights else _FALLBACK_LINE_PX
    gap = line_h * _ROW_GAP
    y = max((b[3] for b in placed), default=-gap) + gap
    default_x = min((b[0] for b in placed), default=0.0)
    out: list[tuple[str, list[float]]] = []
    row_y = row_h = label_right = None
    for line in lines:
        x0, _, x1, _ = line["bbox"]
        text = line["text"]
        plain = _BOLD_RE.sub(r"\1", text).replace("**", "")
        if x1 - x0 < 1:
            x0 = x0 if x0 > 0 else default_x
            x1 = x0 + _text_width(plain, line_h * 0.85)
        joins = row_y is not None and (_PRICE_RE.fullmatch(text.strip()) or x0 >= label_right)
        if not joins:
            if row_y is not None:
                y += row_h + gap
            row_y, row_h = y, line_h
            label_right = x1
        h = _wrap_count(plain, line_h * 0.85, x1 - x0) * line_h
        row_h = max(row_h, h)
        out.append((text, [x0, row_y, x1, row_y + h]))
    return out


def _table_element(table, k: float) -> dict:
    """A detected image table (cells in pixels, each with its OCR lines) as a table_xml element in
    points; every line's font is fitted to its share of the cell."""
    grid, cells = [], []
    for cell in table.cells:
        box = tuple(v * k for v in cell.bbox)
        texts = [_BOLD_RE.sub(r"\1", line["text"]).replace("**", "") for line in cell.lines]
        width = box[2] - box[0] - 2.0  # table_xml's 1 pt cell margins
        height = (box[3] - box[1]) / max(len(texts), 1)
        grid.append(box)
        cells.append(
            {"bbox": box, "lines": [[{"text": t, "font": (_fit_font(t, width, height)[0], "Arial", False, False)}] for t in texts]}
        )
    bbox = [min(b[0] for b in grid), min(b[1] for b in grid), max(b[2] for b in grid), max(b[3] for b in grid)]
    return {"bbox": bbox, "grid_cells": grid, "cells": cells}


def image_docx(lines: list[dict], width_px: int, height_px: int, tables: list | None = None) -> bytes | None:
    """Stitch OCR lines ({text, bbox in image pixels}) into a .docx whose page is the image size
    (96 dpi, no margins), each line pinned to its bbox as a paragraph frame, and each detected table
    (image_table.Table: cells in pixels holding their lines) as a real Word table floated at its place.
    Lines with a collapsed bbox (height under _MIN_LINE_PX) or one squashed against the image bottom
    can't be placed, so _rebuild_rows lays them out below the last placed line in OCR order (keeping
    their x, prices on their label's row) and the page grows to fit: text is never dropped over a bad
    box. Returns None when there is no text."""
    lines = [line for line in lines if line["text"].strip()]
    tables = [t for t in tables or [] if any(c.lines for c in t.cells)]
    if not lines and not tables:
        return None
    heights = [l["bbox"][3] - l["bbox"][1] for l in lines if l["bbox"][3] - l["bbox"][1] >= _MIN_LINE_PX]
    edge = height_px - _EDGE_PX
    inner = [h for l, h in zip(lines, heights) if l["bbox"][3] < edge] or heights
    typical_h = median(inner) if inner else _FALLBACK_LINE_PX

    def unreliable(line: dict) -> bool:
        top, bottom = line["bbox"][1], line["bbox"][3]
        # collapsed (y1 == y2), or squashed against the bottom edge where the model ran out of page
        return bottom - top < _MIN_LINE_PX or (bottom >= edge and bottom - top < _SQUASHED_RATIO * typical_h)

    stacked = [line for line in lines if unreliable(line)]
    placed = [line for line in lines if not unreliable(line)]
    placed.sort(key=lambda line: (line["bbox"][1], line["bbox"][0]))

    boxes = [(line["text"], list(line["bbox"])) for line in placed]
    if stacked:
        boxes += _rebuild_rows(stacked, [b for _, b in boxes])

    page_w = max([width_px] + [b[2] for _, b in boxes])
    page_h = max([height_px] + [b[3] for _, b in boxes])
    k = min(_PX_TO_PT, _MAX_PAGE_PT / max(page_w, page_h))

    layout = _fit_boxes([(text, [v * k for v in bbox]) for text, bbox in boxes], page_w * k)
    page_h_pt = max([page_h * k] + [y + h for _, _, _, y, _, h in layout])

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Pt(page_w * k), Pt(min(page_h_pt, _MAX_PAGE_PT))
    section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Pt(0)
    section.header_distance = section.footer_distance = Pt(0)
    sect_pr = doc.element.body.sectPr
    for text, size, x, y, w, h in layout:
        sect_pr.addprevious(parse_xml(_image_frame_xml(text, size, x, y, w, h)))
    for table in tables:
        element = _table_element(table, k)
        sect_pr.addprevious(parse_xml(table_xml(element, lambda line: line[0]["font"])))
        # an empty paragraph between floating tables keeps Word from merging them into one
        sect_pr.addprevious(parse_xml(f'<w:p {nsdecls("w")}><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr></w:p>'))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
