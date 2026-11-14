import pdfplumber

from ...config import GAP_FACTOR, GAP_SEPARATOR, MARGIN_RATIO

# Words within this many points of top are treated as being on the same visual line.
_LINE_TOP_TOLERANCE = 3


def find_footer_words(page: pdfplumber.page.Page) -> list[dict]:
    band_top = page.height * (1 - MARGIN_RATIO)
    return [w for w in page.extract_words() if w["top"] >= band_top]


def find_header_words(page: pdfplumber.page.Page) -> list[dict]:
    band_bottom = page.height * MARGIN_RATIO
    return [w for w in page.extract_words() if w["bottom"] <= band_bottom]


def page_band(bbox: list[float], page_height: float) -> str | None:
    """"header" / "footer" when bbox lies wholly inside the top / bottom MARGIN_RATIO band of the
    page (the same bands find_header_words / find_footer_words use), else None."""
    if bbox[3] <= page_height * MARGIN_RATIO:
        return "header"
    if bbox[1] >= page_height * (1 - MARGIN_RATIO):
        return "footer"
    return None


def group_lines(words: list[dict]) -> list[list[dict]]:
    # Grouped by vertical range overlap (not just proximity to the *last* word's top) since a
    # short glyph like "-" or "," has a much shallower bounding box than surrounding letters and
    # would otherwise compare as being on a different line even though it's visually the same one.
    ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    for w in ordered:
        if lines:
            line = lines[-1]
            line_top = min(x["top"] for x in line)
            line_bottom = max(x["bottom"] for x in line)
            center = (w["top"] + w["bottom"]) / 2
            if line_top - _LINE_TOP_TOLERANCE <= center <= line_bottom + _LINE_TOP_TOLERANCE:
                line.append(w)
                continue
        lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w["x0"])
    return lines


def join_line_spans(line: list[dict]) -> tuple[str, list[tuple[int, int]]]:
    """join_line's text plus each word's [start, end) char offset in it, so a span of the joined
    text maps back onto the words (and their bboxes) it covers."""
    parts = [line[0]["text"]]
    spans = [(0, len(line[0]["text"]))]
    pos = spans[0][1]
    for prev, word in zip(line, line[1:]):
        wide = word["x0"] - prev["x1"] > GAP_FACTOR * (prev["bottom"] - prev["top"])
        separator = GAP_SEPARATOR if wide else " "
        parts += [separator, word["text"]]
        pos += len(separator)
        spans.append((pos, pos + len(word["text"])))
        pos += len(word["text"])
    return "".join(parts), spans


def join_line(line: list[dict]) -> str:
    """Join a line's words with a space, or GAP_SEPARATOR where the bbox gap to the previous word
    is wide relative to the word height (e.g. left/center/right segments of a running header)."""
    return join_line_spans(line)[0]


def word_entry(w: dict) -> dict:
    return {"text": w["text"], "bbox": [round(w[k], 2) for k in ("x0", "top", "x1", "bottom")]}


def layout_lines(page, x_tolerance_ratio: float, with_words: bool = False) -> list[dict]:
    """Page (or filtered page) text in reading order as one {text, bbox} entry per visual line,
    with widely separated segments on the same line kept apart by GAP_SEPARATOR instead of a
    single space. bbox is [x0, top, x1, bottom] in points. `with_words` also adds the line's
    words as [{text, bbox}]."""
    words = page.extract_words(x_tolerance_ratio=x_tolerance_ratio)
    out = []
    for line in group_lines(words):
        entry = {
            "text": join_line(line),
            "bbox": [
                min(w["x0"] for w in line),
                min(w["top"] for w in line),
                max(w["x1"] for w in line),
                max(w["bottom"] for w in line),
            ],
        }
        if with_words:
            entry["words"] = [word_entry(w) for w in line]
        out.append(entry)
    return out


def layout_text(page, x_tolerance_ratio: float) -> str:
    return "\n".join(line["text"] for line in layout_lines(page, x_tolerance_ratio))


def otsu_threshold(values: list[float], bins: int = 50, value_range: tuple[float, float] = (0.0, 1.0)) -> float:
    """Standard Otsu two-class threshold: the cut point in `values` that maximizes the variance
    between the two groups it splits `values` into. Used to separate a bimodal distribution of
    normalized character gaps into "within a word" (small) vs "between words" (larger) clusters."""
    lo, hi = value_range
    width = (hi - lo) / bins
    hist = [0] * bins
    for v in values:
        hist[min(int((v - lo) / width), bins - 1)] += 1
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_bg, weight_bg = 0.0, 0
    best_variance, best_idx = -1.0, 0
    for i, h in enumerate(hist):
        weight_bg += h
        if weight_bg == 0:
            continue
        weight_fg = total - weight_bg
        if weight_fg == 0:
            break
        sum_bg += i * h
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_all - sum_bg) / weight_fg
        variance_between = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if variance_between > best_variance:
            best_variance, best_idx = variance_between, i
    return lo + (best_idx + 1) * width


def calibrate_x_tolerance_ratio(chars: list[dict], fallback: float, min_samples: int = 30) -> float:
    """Estimate this page's own word-gap threshold (as a fraction of character size) from the
    natural separation between its within-word kerning gaps and its between-word gaps, instead of
    trusting one fixed ratio for every document/font - some PDF generators (esp. justified body
    text) render inter-word spacing as a small position adjustment rather than a space glyph, and
    a fixed absolute point threshold can be too loose to catch it at small font sizes. Falls back
    to `fallback` when there isn't enough text on the page to calibrate confidently (e.g. a title
    page or a scanned/image page)."""
    ratios = [
        gap / a["size"]
        for line in group_lines(chars)
        for a, b in zip(line, line[1:])
        if a["size"] > 0 and 0 < (gap := b["x0"] - a["x1"]) / a["size"] <= 1.0
    ]
    if len(ratios) < min_samples:
        return fallback
    return otsu_threshold(ratios)


def is_inside(obj: dict, bbox: list[float]) -> bool:
    cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
    return bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]


def line_entry(line: list[dict]) -> dict:
    return {
        "text": join_line(line),
        "bbox": [
            min(w["x0"] for w in line),
            min(w["top"] for w in line),
            max(w["x1"] for w in line),
            max(w["bottom"] for w in line),
        ],
        "words": [word_entry(w) for w in line],
    }
