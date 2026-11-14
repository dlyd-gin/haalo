from collections.abc import Callable
from xml.sax.saxutils import escape

from docx.oxml.ns import nsdecls

_TWIPS = 20  # per point
_MIN_SQUEEZE = 0.2  # a table is squeezed into the body area only if at least this fraction fits

Font = tuple[float, str, bool, bool]  # (size pt, family, bold, italic)


def tw(points: float) -> int:
    return round(points * _TWIPS)


def run_xml(text: str, font: Font) -> str:
    size, family, bold, italic = font
    fam = escape(family, {'"': "&quot;"})
    return (
        f'<w:r><w:rPr><w:rFonts w:ascii="{fam}" w:hAnsi="{fam}" w:cs="{fam}"/>'
        f'{"<w:b/>" if bold else ""}{"<w:i/>" if italic else ""}<w:sz w:val="{max(round(size * 2), 1)}"/>'
        f'</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
    )


def _edges(values: list[float], tolerance: float = 0.5) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tolerance:
            out.append(v)
    return out


def _edge_index(edges: list[float], v: float) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def _exact_line(row_height: float, font_size: float = 1.0) -> str:
    """Zero-spacing paragraph properties with an exact line height that fits the row."""
    line = max(tw(min(row_height, font_size * 1.2)), 1)
    return f'<w:spacing w:before="0" w:after="0" w:line="{line}" w:lineRule="exact"/>'


def table_xml(element: dict, font_of: Callable[[list[dict]], Font], body: tuple[float, float] | None = None) -> str:
    """A table as a real Word table floated at its bbox: grid columns/rows from the detected cell
    edges, merged cells as gridSpan/vMerge, the text of each cell from `cells`, each line's font from `font_of(words)`. `body` is the
    (top, bottom) of the area between the header and footer bands: a table reaching outside it is
    squeezed to fit, so it can't lie over them. Rows have exact heights (and cell lines
    exact spacing) so Word can't grow the table past that."""
    cells = element["grid_cells"]
    xs = _edges([v for c in cells for v in (c[0], c[2])])
    ys = _edges([v for c in cells for v in (c[1], c[3])])
    ncols, nrows = len(xs) - 1, len(ys) - 1
    texts = {tuple(round(v, 2) for v in c["bbox"]): c for c in element["cells"]}
    # slot[(r, c)] = ("start", cell, colspan, rowspan, cell_bbox) | ("cont", colspan) | None (uncovered)
    slot: dict[tuple[int, int], tuple] = {}
    for cell in cells:
        c0, c1 = _edge_index(xs, cell[0]), _edge_index(xs, cell[2])
        r0, r1 = _edge_index(ys, cell[1]), _edge_index(ys, cell[3])
        if c1 <= c0 or r1 <= r0 or (r0, c0) in slot:
            continue
        slot[(r0, c0)] = ("start", cell, c1 - c0, r1 - r0)
        for r in range(r0 + 1, r1):
            slot[(r, c0)] = ("cont", c1 - c0)
    top, scale = ys[0], 1.0
    if body:
        # Squeeze in place: only the edge that reaches into a band moves, so the edge facing a
        # neighbouring table/note stays where the PDF has it (shifting would collide with it).
        total = ys[-1] - ys[0]
        new_top, new_bottom = max(ys[0], body[0]), min(ys[-1], body[1])
        if total > 0 and new_bottom - new_top >= max(total * _MIN_SQUEEZE, 10.0):
            top, scale = new_top, (new_bottom - new_top) / total
    row_pts = [(ys[r + 1] - ys[r]) * scale for r in range(nrows)]
    rows = []
    for r in range(nrows):
        tcs, c = [], 0
        while c < ncols:
            entry = slot.get((r, c))
            span = entry[2] if entry and entry[0] == "start" else entry[1] if entry else 1
            span = max(1, min(span, ncols - c))
            width = tw(xs[c + span] - xs[c])
            pr = f'<w:tcW w:w="{width}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "")
            if entry and entry[0] == "cont":
                pr += "<w:vMerge/>"
                body = f'<w:p><w:pPr>{_exact_line(row_pts[r])}</w:pPr></w:p>'
            else:
                if entry and entry[3] > 1:
                    pr += '<w:vMerge w:val="restart"/>'
                info = texts.get(tuple(round(v, 2) for v in entry[1])) if entry else None
                body = ""
                for line in info["lines"] if info else []:
                    font = font_of(line)
                    body += (
                        f"<w:p><w:pPr>{_exact_line(row_pts[r], font[0])}</w:pPr>"
                        + run_xml(" ".join(w["text"] for w in line), font)
                        + "</w:p>"
                    )
                body = body or f'<w:p><w:pPr>{_exact_line(row_pts[r])}</w:pPr></w:p>'
            tcs.append(f"<w:tc><w:tcPr>{pr}</w:tcPr>{body}</w:tc>")
            c += span
        height = tw(row_pts[r])
        rows.append(f'<w:tr><w:trPr><w:trHeight w:val="{height}" w:hRule="exact"/></w:trPr>{"".join(tcs)}</w:tr>')
    border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>' for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join(f'<w:gridCol w:w="{tw(xs[i + 1] - xs[i])}"/>' for i in range(ncols))
    x0 = element["bbox"][0]
    return (
        f'<w:tbl {nsdecls("w")}><w:tblPr>'
        f'<w:tblpPr w:horzAnchor="page" w:vertAnchor="page" w:tblpX="{tw(x0)}" w:tblpY="{tw(top)}"/>'
        f'<w:tblW w:w="{tw(xs[-1] - xs[0])}" w:type="dxa"/><w:tblBorders>{border}</w:tblBorders>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:left w:w="20" w:type="dxa"/><w:right w:w="20" w:type="dxa"/></w:tblCellMar></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>"
        + "".join(rows)
        + "</w:tbl>"
    )
