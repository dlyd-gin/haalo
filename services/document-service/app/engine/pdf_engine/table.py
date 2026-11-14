import io

import pdfplumber

from ...config import X_TOLERANCE_RATIO_FALLBACK
from .layout import calibrate_x_tolerance_ratio, group_lines, join_line, layout_text, word_entry

# A table cell with more words than this is treated as a prose paragraph that happens to sit
# inside a ruled box (e.g. a commentary cell beside a small key/value grid), not tabular data.
_PROSE_CELL_MIN_WORDS = 25

# The text-alignment fallback also fires on ordinary prose, so a candidate must have at least this
# many rows and columns (after cleaning) to be believed.
_MIN_FALLBACK_ROWS = 2
_MIN_FALLBACK_COLS = 2

_TEXT_STRATEGY_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}


def _clean_cell(cell: str | None) -> str:
    return " ".join((cell or "").split())


def _split_prose_cells(rows: list[list[str]]) -> tuple[list[list[str]], list[str]]:
    """Pull prose-length cells out of a table so they render as text instead of one enormous
    Markdown cell. Returns the remaining rows (with columns/rows left empty by the removal
    dropped) and the extracted paragraphs in reading order."""
    paragraphs: list[str] = []
    kept = []
    for row in rows:
        new_row = []
        for cell in row:
            if len(cell.split()) > _PROSE_CELL_MIN_WORDS:
                paragraphs.append(cell)
                new_row.append("")
            else:
                new_row.append(cell)
        kept.append(new_row)
    return kept, paragraphs


def table_to_markdown(rows: list[list[str | None]]) -> tuple[str, list[str]]:
    """Render table rows as a GitHub-flavored Markdown table, the first row being the header.
    Returns (markdown, prose_paragraphs); markdown is "" when nothing tabular remains."""
    cleaned = [[_clean_cell(c) for c in row] for row in rows]
    cleaned, paragraphs = _split_prose_cells(cleaned)
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return "", paragraphs
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    keep_cols = [i for i in range(width) if any(row[i] for row in cleaned)]
    cleaned = [[row[i].replace("|", "\\|") for i in keep_cols] for row in cleaned]

    header, *body = cleaned
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines), paragraphs


def find_tables(page: pdfplumber.page.Page) -> list:
    """Detect tables by ruling lines first; if there are none, retry with pdfplumber's
    text-alignment strategy (borderless tables) and keep only candidates big enough to not be
    ordinary prose."""
    tables = page.find_tables()
    if tables:
        return tables
    candidates = page.find_tables(table_settings=_TEXT_STRATEGY_SETTINGS)
    return [
        t
        for t in candidates
        if len(t.rows) >= _MIN_FALLBACK_ROWS and max((len(r.cells) for r in t.rows), default=0) >= _MIN_FALLBACK_COLS
    ]


def leftover_lines(words: list[dict], cells: list[tuple], first_row_bbox: tuple) -> tuple[list[list[dict]], list[list[dict]]]:
    """Words inside a table's border that fall in none of its cells (e.g. a header line drawn
    across the top of the box, overflow, stray text), as reading-order lines of words, split into
    those above or level with the table's first row (a header line - written before the table)
    and those below it. Coverage is decided by position, never by comparing text, so words that
    also occur inside the table can't mask these."""
    first_row_bottom = first_row_bbox[3]
    orphans = [
        w
        for w in words
        if not any(
            c[0] <= (w["x0"] + w["x1"]) / 2 <= c[2] and c[1] <= (w["top"] + w["bottom"]) / 2 <= c[3] for c in cells
        )
    ]
    above, below = [], []
    for line in group_lines(orphans):
        center = (min(w["top"] for w in line) + max(w["bottom"] for w in line)) / 2
        (above if center < first_row_bottom else below).append(line)
    return above, below


def split_leftovers(words: list[dict], cells: list[tuple], first_row_bbox: tuple) -> tuple[list[str], list[str]]:
    """leftover_lines as joined text lines."""
    above, below = leftover_lines(words, cells, first_row_bbox)
    return [join_line(line) for line in above], [join_line(line) for line in below]


def detect_tables(pdf_page: pdfplumber.page.Page, ratio: float, tables: list | None = None) -> list[tuple]:
    """Tables on the page in top-to-bottom order as (table, markdown, prose_paragraphs), skipping
    tables overlapping an earlier one and degenerate ones that render empty. `tables` are
    already-detected candidates; without them the page is searched (ruled, then text-alignment)."""
    kept, cursor = [], 0.0
    for table in sorted(find_tables(pdf_page) if tables is None else tables, key=lambda t: t.bbox[1]):
        if table.bbox[1] < cursor:  # overlaps a previous table; its content is already covered
            continue
        markdown, paragraphs = table_to_markdown(table.extract(x_tolerance_ratio=ratio))
        if not markdown:  # degenerate: leave its words to the plain-text path instead of losing them
            continue
        kept.append((table, markdown, paragraphs))
        cursor = table.bbox[3]
    return kept


def extract_page_tables(pdf_bytes: bytes, page: int, x_tolerance_ratio: float | None = None) -> dict | None:
    """Convert a single 1-indexed page to Markdown: text outside tables in reading order with
    each table rendered inline as a GFM table. Returns None for a page with no text layer
    (scanned/image-only) - no OCR is attempted. Opens its own pdfplumber.PDF, like
    extract_page_text, so it is safe to run concurrently from multiple threads."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not 1 <= page <= len(pdf.pages):
                raise ValueError(f"page {page} out of range (1-{len(pdf.pages)})")
            pdf_page = pdf.pages[page - 1]
            if not pdf_page.chars:
                return None
            ratio = (
                x_tolerance_ratio
                if x_tolerance_ratio is not None
                else calibrate_x_tolerance_ratio(pdf_page.chars, fallback=X_TOLERANCE_RATIO_FALLBACK)
            )

            kept = detect_tables(pdf_page, ratio)
            bboxes = [table.bbox for table, _, _ in kept]

            def _text_in(y_start: float, y_end: float) -> str:
                """Text whose vertical center is in [y_start, y_end) and that is not inside any
                table bbox - so text beside a table (same rows, outside its border) is kept."""
                def keep(obj: dict) -> bool:
                    cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
                    return y_start <= cy < y_end and not any(
                        bx0 <= cx <= bx1 and btop <= cy <= bbottom for bx0, btop, bx1, bbottom in bboxes
                    )

                return layout_text(pdf_page.filter(keep), ratio).strip()

            def _words_in_bbox(bbox: tuple) -> list[dict]:
                bx0, btop, bx1, bbottom = bbox
                inside = pdf_page.filter(
                    lambda o: bx0 <= (o["x0"] + o["x1"]) / 2 <= bx1 and btop <= (o["top"] + o["bottom"]) / 2 <= bbottom
                )
                return inside.extract_words(x_tolerance_ratio=ratio)

            blocks: list[str] = []
            tables: list[dict] = []
            recovered = False
            cursor = 0.0
            for table, markdown, paragraphs in kept:
                x0, top, x1, bottom = table.bbox
                blocks.append(_text_in(cursor, top))
                above, below = split_leftovers(
                    _words_in_bbox(table.bbox), table.cells, table.rows[0].bbox if table.rows else table.bbox
                )
                if above or below:
                    recovered = True
                blocks.append("\n".join(above))
                blocks.append(_text_in(top, bottom))  # text beside the table, outside its border: written first
                blocks.append(markdown)
                tables.append({"markdown": markdown, "bbox": [x0, top, x1, bottom]})
                blocks.extend(paragraphs)
                blocks.append("\n".join(below))
                cursor = bottom
            blocks.append(_text_in(cursor, float("inf")))
            blocks = [b for b in blocks if b]
            return {"markdown": "\n\n".join(blocks), "tables": tables, "recovered_text": recovered}
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - mirrors /analyze's parse-failure handling
        raise ValueError("invalid PDF") from exc


def table_cells(table, words: list[dict]) -> list[dict]:
    """Non-empty cells of a table as {row, col, text, bbox, words}; row/col index the raw grid
    pdfplumber detected (before empty rows/columns are dropped from the Markdown)."""
    cells = []
    for r, row in enumerate(table.rows):
        for c, cb in enumerate(row.cells):
            if cb is None:
                continue
            inside = [w for w in words if cb[0] <= (w["x0"] + w["x1"]) / 2 <= cb[2] and cb[1] <= (w["top"] + w["bottom"]) / 2 <= cb[3]]
            if not inside:
                continue
            lines = group_lines(inside)
            cells.append(
                {
                    "row": r,
                    "col": c,
                    "text": "\n".join(join_line(line) for line in lines),
                    "bbox": [round(v, 2) for v in cb],
                    "words": [word_entry(w) for line in lines for w in line],
                    "lines": [[word_entry(w) for w in line] for line in lines],
                }
            )
    return cells
