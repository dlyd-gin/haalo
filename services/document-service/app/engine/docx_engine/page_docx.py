import io
import logging
import re
from statistics import median

import pdfplumber
from docx import Document
from docx.enum.section import WD_SECTION
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt

from ...config import GAP_FACTOR
from ..pdf_engine.elements import page_elements
from ..pdf_engine.layout import is_inside, line_entry, page_band
from .ooxml import run_xml, table_xml, tw

logger = logging.getLogger(__name__)

_BAND_GAP = 2.0  # points kept clear between the header/footer text and the body area
_MIN_BODY_RATIO = 0.1  # the body area keeps at least this fraction of the page height


_EMU = 12700  # per point
_FONT_FAMILIES = (("helvetica", "Arial"), ("arial", "Arial"), ("times", "Times New Roman"), ("courier", "Courier New"))


def _segments(words: list[dict]) -> list[list[dict]]:
    """Split a line's {text, bbox} words into segments where join_line would put GAP_SEPARATOR."""
    segments = [[words[0]]]
    for prev, word in zip(words, words[1:]):
        if word["bbox"][0] - prev["bbox"][2] > GAP_FACTOR * (prev["bbox"][3] - prev["bbox"][1]):
            segments.append([])
        segments[-1].append(word)
    return segments


def _words_bbox(words: list[dict]) -> list[float]:
    return [
        min(w["bbox"][0] for w in words),
        min(w["bbox"][1] for w in words),
        max(w["bbox"][2] for w in words),
        max(w["bbox"][3] for w in words),
    ]


def _font_of(chars: list[dict], bbox: list[float]) -> tuple[float, str, bool, bool]:
    """(size in pt, family, bold, italic) of the glyphs whose center lies in bbox."""
    inside = [c for c in chars if is_inside(c, bbox)]
    if not inside:
        return max(bbox[3] - bbox[1], 1.0) * 0.85, "Arial", False, False
    size = median(c["size"] for c in inside)
    names = [c["fontname"] for c in inside]
    name = max(set(names), key=names.count)
    base = name.split("+")[-1]
    lower = base.lower()
    family = next((fam for key, fam in _FONT_FAMILIES if key in lower), re.split(r"[-,]", base)[0] or "Arial")
    return size, family, "bold" in lower, "italic" in lower or "oblique" in lower


def _frame_xml(words: list[dict], chars: list[dict]) -> str:
    """One text segment as a paragraph frame pinned to the page at its bbox."""
    x0, top, x1, bottom = bbox = _words_bbox(words)
    font = _font_of(chars, bbox)
    slack = font[0]  # lets Word's substitute font run a little wider without wrapping the segment
    return (
        f'<w:p {nsdecls("w")}><w:pPr>'
        f'<w:framePr w:w="{tw(x1 - x0 + slack)}" w:h="{tw(bottom - top)}" w:hRule="exact" w:hSpace="0" '
        f'w:vSpace="0" w:wrap="around" w:vAnchor="page" w:hAnchor="page" w:x="{tw(x0)}" w:y="{tw(top)}"/>'
        f'<w:spacing w:before="0" w:after="0" w:line="{tw(bottom - top)}" w:lineRule="exact"/></w:pPr>'
        + run_xml(" ".join(w["text"] for w in words), font)
        + "</w:p>"
    )


def _anchor_picture(doc, png: bytes, bbox: list[float]) -> None:
    """Add a picture pinned to the page at bbox (behind text): python-docx only makes inline
    pictures, so the inline drawing is rewritten into a wp:anchor."""
    x0, top, x1, bottom = bbox
    para = doc.add_paragraph()
    para.paragraph_format.space_before = para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = Pt(1)
    run = para.add_run()
    run.add_picture(io.BytesIO(png), width=Pt(x1 - x0), height=Pt(bottom - top))
    inline = run._r.xpath(".//wp:inline")[0]
    ns = nsdecls("wp", "a")
    anchor = parse_xml(
        f'<wp:anchor {ns} distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="0" '
        f'behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        f'<wp:positionH relativeFrom="page"><wp:posOffset>{round(x0 * _EMU)}</wp:posOffset></wp:positionH>'
        f'<wp:positionV relativeFrom="page"><wp:posOffset>{round(top * _EMU)}</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{round((x1 - x0) * _EMU)}" cy="{round((bottom - top) * _EMU)}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/></wp:anchor>'
    )
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        anchor.append(inline.xpath(f"./{tag}")[0])
    inline.getparent().replace(inline, anchor)


def _collapse_paragraph(p_el) -> None:
    """Shrink a paragraph that only exists for Word's structure (a section break, an empty header)
    to a 1pt line, so it can't push pinned content or spill onto an extra page."""
    spacing = p_el.get_or_add_pPr().get_or_add_spacing()  # schema order kept (before a w:sectPr)
    for name, value in (("before", "0"), ("after", "0"), ("line", "20"), ("lineRule", "exact")):
        spacing.set(qn(f"w:{name}"), value)


def _render_page(doc, section, pdf_page, x_tolerance_ratio: float | None, dpi: int, own_hdrftr: bool) -> bool:
    """Pin one pdfplumber page's elements into `section`, the document's last section (content is
    emitted before body.sectPr). `own_hdrftr` gives the section its own header/footer even when this
    page has none, so a later section can't inherit the previous page's. Returns False, leaving the
    section untouched, when the page has neither a text layer nor images."""
    result = page_elements(pdf_page, x_tolerance_ratio, dpi)
    if result is None:
        return False
    elements, _ = result
    chars = pdf_page.chars

    flat: list[dict] = []
    for e in elements:
        flat.append(e)
        for line, _above in e.get("leftovers", []):
            entry = line_entry(line)
            flat.append({"kind": "text", **entry})
    flat.sort(key=lambda e: (e["bbox"][1], e["bbox"][0]))

    section.page_width, section.page_height = Pt(pdf_page.width), Pt(pdf_page.height)
    section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Pt(0)
    section.header_distance = section.footer_distance = Pt(0)
    body = doc.element.body
    sect_pr = body.sectPr
    height = pdf_page.height

    # Pass 1: which text segments belong to the header/footer, and so how much of the page
    # they reserve. Everything is pinned to the page, so the margins don't move it.
    placed: list[tuple[dict, list[tuple[list[dict], str | None]]]] = []
    bands: dict[str, list[list[float]]] = {"header": [], "footer": []}
    for e in flat:
        segments = []
        if e["kind"] == "text":
            band = page_band(e["bbox"], height)
            for segment in _segments(e["words"]):
                segments.append((segment, band))
                if band:
                    bands[band].append(_words_bbox(segment))
        placed.append((e, segments))
    top_margin = max(b[3] for b in bands["header"]) + _BAND_GAP if bands["header"] else 0.0
    bottom_margin = height - min(b[1] for b in bands["footer"]) + _BAND_GAP if bands["footer"] else 0.0
    room = height * (1 - _MIN_BODY_RATIO)
    if top_margin + bottom_margin > room:
        scale = room / (top_margin + bottom_margin)
        top_margin, bottom_margin = top_margin * scale, bottom_margin * scale
    section.top_margin, section.bottom_margin = Pt(top_margin), Pt(bottom_margin)
    if bands["header"]:
        section.header_distance = Pt(max(min(b[1] for b in bands["header"]), 0))
    if bands["footer"]:
        section.footer_distance = Pt(max(height - max(b[3] for b in bands["footer"]), 0))

    # Pass 2: emit. Tables are kept inside the body area between the header and footer.
    parts = {"header": None, "footer": None}
    for e, segments in placed:
        if e["kind"] == "text":
            for segment, band in segments:
                frame = parse_xml(_frame_xml(segment, chars))
                if band is None:
                    sect_pr.addprevious(frame)
                    continue
                if parts[band] is None:  # created lazily: no part for a page without one
                    part = section.header if band == "header" else section.footer
                    part.is_linked_to_previous = False
                    for stale in list(part._element):  # python-docx's default empty paragraph
                        part._element.remove(stale)
                    parts[band] = part._element
                parts[band].append(frame)
        elif e["kind"] == "table":
            sect_pr.addprevious(parse_xml(table_xml(e, lambda line: _font_of(chars, _words_bbox(line)), (top_margin, height - bottom_margin))))
            sect_pr.addprevious(parse_xml(f'<w:p {nsdecls("w")}><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/></w:pPr></w:p>'))
        else:
            _anchor_picture(doc, e["png"], e["bbox"])
    if own_hdrftr:
        for band, part in (("header", section.header), ("footer", section.footer)):
            if parts[band] is None:
                part.is_linked_to_previous = False  # an empty part of its own, not the previous page's
                for p_el in part._element.xpath("./w:p"):
                    _collapse_paragraph(p_el)
    return True


def pages_docx(pdf_bytes: bytes, pages: list[int], x_tolerance_ratio: float | None, dpi: int) -> bytes | None:
    """Stitch 1-indexed pages into one .docx that reproduces their layout, one Word section per
    page: each section is its PDF page's size with no margins and every element is pinned to the
    page at its bbox (text segments as paragraph frames, tables as floating tables, images as
    anchored pictures), in source reading order. Text inside a table or image bbox is not repeated.
    Pages with neither a text layer nor images are skipped; returns None when every page is like
    that. Opens its own pdfplumber.PDF, so it is safe to run on a worker thread."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pages:
                if not 1 <= page <= len(pdf.pages):
                    raise ValueError(f"page {page} out of range (1-{len(pdf.pages)})")
            doc = Document()
            rendered = 0
            for page in pages:
                # A section break freezes the finished page's settings into its own sectPr and leaves
                # body.sectPr (the last section) for the next page; added only once that page exists.
                if rendered:
                    section = doc.add_section(WD_SECTION.NEW_PAGE)
                    _collapse_paragraph(doc.element.body.sectPr.getprevious())
                else:
                    section = doc.sections[0]
                if _render_page(doc, section, pdf.pages[page - 1], x_tolerance_ratio, dpi, own_hdrftr=rendered > 0):
                    rendered += 1
                elif rendered:  # nothing on this page: drop the section break just added
                    _drop_last_section(doc)
            if not rendered:
                return None
            out = io.BytesIO()
            doc.save(out)
            return out.getvalue()
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - mirrors /analyze's parse-failure handling
        # Not always a parse failure (python-docx or layout code can raise too): keep the cause visible.
        logger.exception("pages_docx failed")
        raise ValueError(f"invalid PDF ({type(exc).__name__}: {exc})") from exc


def _drop_last_section(doc) -> None:
    """Undo add_section: the break paragraph's sectPr (the previous page's settings, header/footer
    references included) becomes body.sectPr again."""
    body = doc.element.body
    break_p = body.sectPr.getprevious()
    frozen = break_p.pPr.sectPr
    body.sectPr.getparent().replace(body.sectPr, frozen)
    body.remove(break_p)


def page_docx(pdf_bytes: bytes, page: int, x_tolerance_ratio: float | None, dpi: int) -> bytes | None:
    """One page as pages_docx: None when the page has neither a text layer nor images."""
    return pages_docx(pdf_bytes, [page], x_tolerance_ratio, dpi)
