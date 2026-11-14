import copy
import io

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from ...config import HIGHLIGHT_COLOR


def _text_paragraphs(doc) -> list[tuple[Paragraph, list[Run], str]]:
    """Every paragraph with visible text (body and table cells, document order) as
    (paragraph, its runs, its text). The text is the concatenation of the run texts, so a char
    offset into it maps straight onto the runs. Index in this list == line number."""
    out = []
    for p_el in doc.element.body.iter(qn("w:p")):
        paragraph = Paragraph(p_el, doc)
        runs = [Run(r_el, paragraph) for r_el in p_el.iterfind(".//" + qn("w:r"))]
        text = "".join(run.text for run in runs)
        if text.strip():
            out.append((paragraph, runs, text))
    return out


def docx_lines(docx_bytes: bytes) -> list[str]:
    """Pure: the text lines (one per non-blank paragraph) that /ground-state grounds against."""
    return [text for _, _, text in _text_paragraphs(Document(io.BytesIO(docx_bytes)))]


def _split_run_at(paragraph: Paragraph, offset: int) -> None:
    """Split the run that strictly contains char `offset` of the paragraph text into two runs
    with identical formatting; no-op when `offset` already falls on a run boundary."""
    pos = 0
    for r_el in paragraph._p.iterfind(".//" + qn("w:r")):
        run = Run(r_el, paragraph)
        text = run.text
        if pos < offset < pos + len(text):
            clone = copy.deepcopy(r_el)
            r_el.addnext(clone)
            run.text = text[: offset - pos]
            Run(clone, paragraph).text = text[offset - pos :]
            return
        pos += len(text)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def valid_groundings(groundings: list[dict], lines: list[str]) -> dict[int, list[tuple[int, int]]]:
    """Group groundings by line, dropping anything out of range or empty. Format-agnostic: the
    PDF highlighter shares it."""
    by_line: dict[int, list[tuple[int, int]]] = {}
    for g in groundings:
        line, start, end = g.get("line"), g.get("start"), g.get("end")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (line, start, end)):
            continue
        if not 0 <= line < len(lines) or not 0 <= start < end <= len(lines[line]):
            continue
        by_line.setdefault(line, []).append((start, end))
    return {line: _merge_spans(spans) for line, spans in by_line.items()}


def highlight_snippets(lines: list[str], suggestions: list[dict]) -> list[str]:
    """Pure: the text of each valid, merged span, in document order (what highlight_docx marks)."""
    by_line = valid_groundings(suggestions, lines)
    return [lines[line][start:end] for line in sorted(by_line) for start, end in by_line[line]]


def highlight_docx(docx_bytes: bytes, groundings: list[dict]) -> bytes | None:
    """Pure: highlight each grounded [start, end) span of its line, splitting runs at the span
    edges so only the grounded characters are marked. Returns None when no grounding is valid."""
    doc = Document(io.BytesIO(docx_bytes))
    paragraphs = _text_paragraphs(doc)
    by_line = valid_groundings(groundings, [text for _, _, text in paragraphs])
    if not by_line:
        return None

    color = WD_COLOR_INDEX[HIGHLIGHT_COLOR]
    for line, spans in by_line.items():
        paragraph = paragraphs[line][0]
        for start, end in spans:
            _split_run_at(paragraph, start)
            _split_run_at(paragraph, end)
            pos = 0
            for r_el in paragraph._p.iterfind(".//" + qn("w:r")):
                run = Run(r_el, paragraph)
                run_len = len(run.text)
                if run_len and start <= pos and pos + run_len <= end:
                    run.font.highlight_color = color
                pos += run_len

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
