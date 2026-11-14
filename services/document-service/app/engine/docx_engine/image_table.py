import io
import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import median

import cv2
import numpy as np
from PIL import Image

from .image_docx import _MIN_LINE_PX, _text_width

_LINE_LEN_RATIO = 25  # a ruling line is at least 1/25 of the image width (or 1/40 of its height)
_LINE_LEN_RATIO_V = 40
_MIN_CELL_PX = 8  # an enclosed area narrower or shorter than this is a glyph gap, not a cell
_MAX_CELL_AREA = 0.25  # an enclosed area bigger than this fraction of the image is the page, not a cell
_SNAP_RATIO = 0.012  # cell edges within this fraction of the image's long side are one grid line ...
_SNAP_CELL = 0.45  # ... capped at this fraction of the median cell (a cell squeezed to nothing is dropped)
_MIN_TABLE_CELLS = 4
_EDGE_PX = 2  # a line ending this close to the image bottom was clamped by the model: its y is unusable
_INK_INSET = 3  # px kept clear of the ruling when looking for ink in a cell
_INK_RATIO = 0.02  # a cell with more ink pixels than this fraction holds text
_CROP_MARGIN = 8  # white px around a band crop, so glyphs at its edge are not cut off for the VLM
_CROP_SCALE = 2  # band crops are upscaled so the VLM sees the few glyphs at a readable size
_SPACE_RE = re.compile(r"\s+")
_COVERED = 0.8  # a doubtful page line is dropped when this share of its characters is in the table


@dataclass
class Cell:
    bbox: list[float]  # [x0, y0, x1, y1] in image pixels, snapped to the table's grid lines
    rows: tuple[int, int]  # grid line indices (first, last)
    cols: tuple[int, int]
    inked: bool = False  # the image shows text in it
    lines: list[dict] = field(default_factory=list)  # OCR {text, bbox} lines, in reading order


@dataclass
class Table:
    cells: list[Cell]

    @property
    def bbox(self) -> list[float]:
        return [
            min(c.bbox[0] for c in self.cells),
            min(c.bbox[1] for c in self.cells),
            max(c.bbox[2] for c in self.cells),
            max(c.bbox[3] for c in self.cells),
        ]


@dataclass
class Band:
    """One table row (or the rows a merged cell spans) with text in it, read by its own OCR call:
    the VLM's boxes on a whole dense page are too far off to tell cells apart, and it skips lines."""

    cells: list[Cell]
    box: list[int]  # crop in image pixels (may reach past the image by _CROP_MARGIN)
    png: bytes  # the crop, upscaled by _CROP_SCALE
    page_lines: list[dict]  # the page OCR's lines in this band: the fallback if the band can't be read


@dataclass
class ImageLayout:
    tables: list[Table]
    bands: list[Band]
    free: list[dict]  # page OCR lines outside every table, pinned as frames
    doubtful: list[dict]  # page OCR lines with an unusable y: kept only if the table doesn't already hold their text
    image: Image.Image  # the upload as RGB, for cell crops

    def fill(self, band: Band, lines: list[dict] | None) -> bool:
        """Put the OCR lines read from band.png (crop pixels) into the band's cells; None falls back
        to the page OCR's lines for the band. True when the lines paired one-to-one with the inked
        cells; otherwise they were placed by position, which the caller should confirm cell by cell."""
        lines = band.page_lines if lines is None else _from_crop(band, lines)
        return _match(band.cells, [l for l in lines if l["text"].strip()])

    def cell_band(self, cell: Cell) -> Band:
        """A crop of one cell, to read it alone when its row's read didn't pair with the cells."""
        return _band(self.image, [cell], [])

    def fill_cell(self, crop: Band, lines: list[dict]) -> None:
        """Replace the cell's text with what was read from its own crop (kept as is if nothing was)."""
        lines = [l for l in _from_crop(crop, lines) if l["text"].strip()]
        if lines:
            crop.cells[0].lines = lines
            _tidy(crop.cells[0])

    def lines(self) -> list[dict]:
        """The lines left for the frame layout, once the bands are filled."""
        table_chars = Counter("".join(_compact(l["text"]) for t in self.tables for c in t.cells for l in c.lines))

        def in_table(line: dict) -> bool:
            chars = Counter(_compact(line["text"]))
            return sum(min(n, table_chars[ch]) for ch, n in chars.items()) >= _COVERED * sum(chars.values())

        return self.free + [l for l in self.doubtful if not in_table(l)]


def _from_crop(band: Band, lines: list[dict]) -> list[dict]:
    """OCR lines in band.png pixels -> image pixels."""
    x, y = band.box[0], band.box[1]
    return [
        {"text": l["text"], "bbox": [x + l["bbox"][0] / _CROP_SCALE, y + l["bbox"][1] / _CROP_SCALE,
                                     x + l["bbox"][2] / _CROP_SCALE, y + l["bbox"][3] / _CROP_SCALE]}
        for l in lines
    ]


def read_layout(data: bytes, lines: list[dict]) -> ImageLayout:
    """Find the ruled tables in an image and split the page OCR lines into those outside every table
    (frames) and those inside (only a fallback: each band of a table is read again on its own)."""
    with Image.open(io.BytesIO(data)) as image:
        rgb = image.convert("RGB")
    gray = np.asarray(rgb.convert("L"))
    ink, ruling = _masks(gray)
    text_ink = cv2.bitwise_and(ink, cv2.bitwise_not(ruling))
    tables = _tables(ruling)
    for table in tables:
        for cell in table.cells:
            cell.inked = _inked(text_ink, cell.bbox)
    tables = [t for t in tables if any(c.inked for c in t.cells)]  # an empty grid is not worth a table
    height = gray.shape[0]
    free, doubtful, inside = [], [], []
    for line in lines:
        x0, y0, x1, y1 = line["bbox"]
        if y1 - y0 < _MIN_LINE_PX or y1 >= height - _EDGE_PX:
            doubtful.append(line)
        elif any(_inside(t.bbox, (x0 + x1) / 2, (y0 + y1) / 2) for t in tables):
            inside.append(line)
        else:
            free.append(line)
    bands = []
    for table in tables:
        for cells in _band_cells(table.cells):
            if any(c.inked for c in cells):
                box = Table(cells).bbox
                page = [l for l in inside if _inside(box, (l["bbox"][0] + l["bbox"][2]) / 2, (l["bbox"][1] + l["bbox"][3]) / 2)]
                bands.append(_band(rgb, cells, page))
    return ImageLayout(tables, bands, free, doubtful, rgb)


def _masks(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(ink, ruling): every dark pixel, and only the long horizontal/vertical strokes among them,
    thickened a little so slightly broken or skewed joints still close each cell."""
    h, w = gray.shape
    block = max(15, (min(h, w) // 40) | 1)
    ink = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 10)
    t = max(3, (min(h, w) // 200) | 1)
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // _LINE_LEN_RATIO, 10), 1)))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // _LINE_LEN_RATIO_V, 10))))
    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (3 * t, t)))
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (t, 3 * t)))
    return ink, cv2.bitwise_or(horiz, vert)


def _tables(ruling: np.ndarray) -> list[Table]:
    """Cells are the areas the ruling encloses (so irregular grids and merged cells come for free);
    touching cells form one table, whose cell edges are snapped onto shared grid lines."""
    h, w = ruling.shape
    _, _, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_not(ruling), connectivity=4)
    boxes = []
    for x, y, bw, bh, _ in stats[1:].tolist():  # label 0 is the ruling itself
        touches_edge = x == 0 or y == 0 or x + bw >= w or y + bh >= h
        if not touches_edge and bw >= _MIN_CELL_PX and bh >= _MIN_CELL_PX and bw * bh <= _MAX_CELL_AREA * w * h:
            boxes.append([x, y, x + bw, y + bh])
    if not boxes:
        return []
    tol_x = min(_SNAP_RATIO * max(h, w), _SNAP_CELL * median(b[2] - b[0] for b in boxes))
    tol_y = min(_SNAP_RATIO * max(h, w), _SNAP_CELL * median(b[3] - b[1] for b in boxes))
    tables = []
    for group in _touching(boxes, tol_x, tol_y):
        table = _grid(group, tol_x, tol_y)
        if table:
            tables.append(table)
    return tables


def _touching(boxes: list[list[int]], tol_x: float, tol_y: float) -> list[list[list[int]]]:
    """Group boxes whose edges are within the snap tolerance of each other (union-find)."""
    parent = list(range(len(boxes)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if a[0] - tol_x <= b[2] and b[0] - tol_x <= a[2] and a[1] - tol_y <= b[3] and b[1] - tol_y <= a[3]:
                parent[root(i)] = root(j)
    groups: dict[int, list[list[int]]] = {}
    for i, box in enumerate(boxes):
        groups.setdefault(root(i), []).append(box)
    return list(groups.values())


def _snap(values: list[float], tol: float) -> tuple[list[float], dict[float, int]]:
    """Cluster sorted values (a cluster spans at most tol from its first value) into grid lines at
    the cluster means; returns the lines and each value's line index."""
    lines: list[float] = []
    index: dict[float, int] = {}
    group: list[float] = []
    for v in sorted(set(values)):
        if group and v - group[0] > tol:
            lines.append(sum(group) / len(group))
            group = []
        group.append(v)
        index[v] = len(lines)
    lines.append(sum(group) / len(group))
    return lines, index


def _grid(boxes: list[list[int]], tol_x: float, tol_y: float) -> Table | None:
    xs, xi = _snap([v for b in boxes for v in (b[0], b[2])], tol_x)
    ys, yi = _snap([v for b in boxes for v in (b[1], b[3])], tol_y)
    if len(boxes) < _MIN_TABLE_CELLS or len(xs) < 3 or len(ys) < 3:
        return None
    taken: set[tuple[int, int]] = set()
    cells = []
    for b in sorted(boxes, key=lambda b: (b[1], b[0])):
        c0, c1, r0, r1 = xi[b[0]], xi[b[2]], yi[b[1]], yi[b[3]]
        if c1 <= c0 or r1 <= r0:  # narrower than the snap tolerance: a sliver between lines, not a cell
            continue
        slots = {(r, c) for r in range(r0, r1) for c in range(c0, c1)}
        if slots & taken:  # skew made two areas claim one grid slot: keep the first
            continue
        taken |= slots
        cells.append(Cell([xs[c0], ys[r0], xs[c1], ys[r1]], (r0, r1), (c0, c1)))
    return Table(cells)


def _band_cells(cells: list[Cell]) -> list[list[Cell]]:
    """Cells grouped by grid row, rows joined while a merged cell spans them. A group spanning
    several rows is split at the column lines no cell crosses (side-by-side blocks whose rows don't
    line up, like a menu's left and right halves) and each side is grouped again."""
    spans: list[list[int]] = []
    for r0, r1 in sorted({c.rows for c in cells}):
        if spans and r0 < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], r1)
        else:
            spans.append([r0, r1])
    out = []
    for s in spans:
        group = [c for c in cells if s[0] <= c.rows[0] and c.rows[1] <= s[1]]
        sides = _split_columns(group) if len({c.rows for c in group}) > 1 else [group]
        if len(sides) == 1:
            out.append(group)
        else:
            for side in sides:
                out.extend(_band_cells(side))
    return out


def _split_columns(cells: list[Cell]) -> list[list[Cell]]:
    lo, hi = min(c.cols[0] for c in cells), max(c.cols[1] for c in cells)
    cuts = [x for x in range(lo + 1, hi) if not any(c.cols[0] < x < c.cols[1] for c in cells)]
    bounds = [lo, *cuts, hi]
    sides = [[c for c in cells if a <= c.cols[0] and c.cols[1] <= b] for a, b in zip(bounds, bounds[1:])]
    return [side for side in sides if side]


def _band(image: Image.Image, cells: list[Cell], page_lines: list[dict]) -> Band:
    """Only the band's own cells, pasted on white: no slivers of the neighbouring rows' text."""
    x0, y0, _, _ = Table(cells).bbox
    left, top = round(x0) - _CROP_MARGIN, round(y0) - _CROP_MARGIN
    right = max(round(c.bbox[2]) for c in cells) + _CROP_MARGIN
    bottom = max(round(c.bbox[3]) for c in cells) + _CROP_MARGIN
    canvas = Image.new("RGB", (right - left, bottom - top), "white")
    for cell in cells:
        box = tuple(round(v) for v in cell.bbox)
        canvas.paste(image.crop(box), (box[0] - left, box[1] - top))
    crop = canvas.resize((canvas.width * _CROP_SCALE, canvas.height * _CROP_SCALE), Image.LANCZOS)
    out = io.BytesIO()
    crop.save(out, format="PNG")
    return Band(sorted(cells, key=lambda c: c.cols), [left, top, right, bottom], out.getvalue(), page_lines)


def _inked(text_ink: np.ndarray, bbox: list[float]) -> bool:
    x0, y0, x1, y1 = (round(v) for v in bbox)
    region = text_ink[y0 + _INK_INSET : y1 - _INK_INSET, x0 + _INK_INSET : x1 - _INK_INSET]
    return region.size > 0 and np.count_nonzero(region) / region.size > _INK_RATIO


def _inside(bbox: list[float], x: float, y: float) -> bool:
    return bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]


def _distance(bbox: list[float], x: float, y: float) -> float:
    dx = max(bbox[0] - x, 0.0, x - bbox[2])
    dy = max(bbox[1] - y, 0.0, y - bbox[3])
    return dx * dx + dy * dy


def _compact(text: str) -> str:
    return _SPACE_RE.sub("", text.replace("**", ""))


def _match(cells: list[Cell], lines: list[dict]) -> bool:
    """Put a band's OCR lines into its cells. Text only goes to cells that show ink. In a one-row
    band with exactly one line per inked cell, lines pair with cells left to right, whatever their
    boxes say (returns True); otherwise each line goes to the cell under it, split across cells on
    whitespace (returns False: the VLM's x is unreliable, so this is only a best guess)."""
    targets = [c for c in cells if c.inked] or cells
    one_row = len({c.rows for c in cells}) == 1
    if one_row:  # y is meaningless inside one row; pin it so only x decides
        top, bottom = cells[0].bbox[1], cells[0].bbox[3]
        lines = [{"text": l["text"], "bbox": [l["bbox"][0], top, l["bbox"][2], bottom]} for l in lines]
    paired = one_row and len(lines) == len(targets)
    if paired:
        for line, cell in zip(sorted(lines, key=lambda l: l["bbox"][0]), targets):
            cell.lines.append(line)
    elif lines:
        # The VLM's x is often scaled or shifted as a whole; place the lines both as given and with
        # their extent fitted onto the inked cells', and keep whichever leaves fewer inked cells empty.
        best: list[Cell] | None = None
        for candidate in (lines, _fit_extent(lines, targets)):
            trial = [Cell(c.bbox, c.rows, c.cols, c.inked) for c in targets]
            for line in candidate:
                _place(trial, line)
            if best is None or sum(not c.lines for c in trial) < sum(not c.lines for c in best):
                best = trial
        for cell, placed in zip(targets, best):
            cell.lines.extend(placed.lines)
    for cell in cells:
        _tidy(cell)
    return paired


def _tidy(cell: Cell) -> None:
    """Order a cell's lines top to bottom, joining pieces of one visual line (the VLM may read
    '品 名' as '品' and '名') into a single line, left to right."""
    rows: list[list[dict]] = []
    for line in sorted(cell.lines, key=lambda l: (l["bbox"][1], l["bbox"][0])):
        if rows:
            last = rows[-1][0]["bbox"]
            overlap = min(last[3], line["bbox"][3]) - max(last[1], line["bbox"][1])
            if overlap >= 0.5 * min(last[3] - last[1], line["bbox"][3] - line["bbox"][1]):
                rows[-1].append(line)
                continue
        rows.append([line])
    cell.lines = []
    for row in rows:
        row.sort(key=lambda l: l["bbox"][0])
        cell.lines.append({
            "text": " ".join(l["text"].strip() for l in row),
            "bbox": [row[0]["bbox"][0], min(l["bbox"][1] for l in row), max(l["bbox"][2] for l in row), max(l["bbox"][3] for l in row)],
        })


def _fit_extent(lines: list[dict], cells: list[Cell]) -> list[dict]:
    """The lines with x stretched/shifted so their overall extent matches the cells'."""
    lx0, lx1 = min(l["bbox"][0] for l in lines), max(l["bbox"][2] for l in lines)
    cx0, cx1 = min(c.bbox[0] for c in cells), max(c.bbox[2] for c in cells)
    if lx1 - lx0 < 1:
        return lines
    s = (cx1 - cx0) / (lx1 - lx0)
    return [
        {"text": l["text"], "bbox": [cx0 + (l["bbox"][0] - lx0) * s, l["bbox"][1], cx0 + (l["bbox"][2] - lx0) * s, l["bbox"][3]]}
        for l in lines
    ]


def _place(cells: list[Cell], line: dict) -> None:
    """Add an OCR line to the cell under its centre. A line whose box runs across several cells of
    its row (the VLM read 'name  price' as one line) is split on whitespace, each word going to the
    cell under its estimated x."""
    x0, y0, x1, y1 = line["bbox"]
    cy = (y0 + y1) / 2
    words = line["text"].split()
    crossed = [c for c in cells if c.bbox[1] <= cy <= c.bbox[3] and min(x1, c.bbox[2]) - max(x0, c.bbox[0]) > 0]
    if len(crossed) < 2 or len(words) < 2:
        cell = min(cells, key=lambda c: _distance(c.bbox, (x0 + x1) / 2, cy))
        cell.lines.append(line)
        return
    text = line["text"]
    scale, pos = (x1 - x0) / (_text_width(text, 1.0) or 1.0), 0  # em -> px along the line's box
    parts: dict[int, list[tuple[str, float, float]]] = {}
    for word in words:
        start = text.index(word, pos)
        left = x0 + _text_width(text[:start], 1.0) * scale
        right = left + _text_width(word, 1.0) * scale
        pos = start + len(word)
        k = min(range(len(crossed)), key=lambda j: _distance(crossed[j].bbox, (left + right) / 2, cy))
        parts.setdefault(k, []).append((word, left, right))
    for k, items in parts.items():
        crossed[k].lines.append({"text": " ".join(t for t, _, _ in items), "bbox": [items[0][1], y0, items[-1][2], y1]})
