import logging
import re
from typing import Any

WHITESPACE = re.compile(r"\s+")

logger = logging.getLogger(__name__)

CROSS_LINE_MAX = 5 # how many following lines a quote may run over (document lines are visual wraps)


def _find_in_text(text: str, quote: str) -> tuple[int, int, str] | None:
    """(start, end, strategy) of `quote` in `text`: exact, then case-insensitive, then
    whitespace-insensitive (tokens separated by any whitespace run)."""
    idx = text.find(quote)
    if idx != -1:
        return idx, idx + len(quote), "exact"
    idx = text.lower().find(quote.lower())
    if idx != -1:
        return idx, idx + len(quote), "case-insensitive"
    pattern = r"\s+".join(re.escape(token) for token in WHITESPACE.split(quote))
    found = re.search(pattern, text, re.IGNORECASE)
    if found is None:
        return None
    return found.start(), found.end(), "whitespace-insensitive"


def _locate_quote(context: list[str], line_no: int, quote: str) -> tuple[list[tuple[int, int, int]], str]:
    """Resolve a quote starting at `line_no` to one (line, start, end) span per touched line.
    Order: inside the line itself, then across the following lines (joined with a space), then on
    the nearest other line holding it (the model miscounts line numbers on long lists), then the whole
    line as a fallback so a right line pick with a slightly wrong quote still grounds."""
    line = context[line_no]
    found = _find_in_text(line, quote)
    if found is not None:
        return [(line_no, found[0], found[1])], found[2]

    window = context[line_no : line_no + 1 + CROSS_LINE_MAX]
    joined = " ".join(window)
    found = _find_in_text(joined, quote)
    if found is not None:
        spans = []
        line_start = 0
        for offset, text in enumerate(window):
            line_end = line_start + len(text)
            start, end = max(found[0], line_start), min(found[1], line_end)
            if start < end:
                spans.append((line_no + offset, start - line_start, end - line_start))
            line_start = line_end + 1  # the joining space
        if spans:
            return spans, "cross-line " + found[2]

    relocated = _find_nearest(context, line_no, quote)
    if relocated is not None:
        other_no, (start, end, strategy) = relocated
        return [(other_no, start, end)], "relocated " + strategy

    if line.strip():
        return [(line_no, 0, len(line))], "whole-line fallback"
    return [], "none"


def _find_nearest(context: list[str], line_no: int, quote: str) -> tuple[int, tuple[int, int, str]] | None:
    """(line, (start, end, strategy)) of `quote` on the line nearest `line_no` that holds it, or None."""
    for other_no in sorted(range(len(context)), key=lambda i: abs(i - line_no)):
        if other_no != line_no and (found := _find_in_text(context[other_no], quote)) is not None:
            return other_no, found
    return None


def resolve_spans(items: list[dict[str, Any]], context: list[str]) -> list[dict[str, Any]]:
    """Turn the model's quotes into char offsets computed in code (the LLM can't count reliably).
    A quote running over several lines yields one span per line. Items with an out-of-range line
    or a blank quote are dropped. An item's optional "reason" is copied onto each of its spans."""
    spans: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int]] = set()
    for item in items:
        line_no = item["line"]
        quote = item["quote"].strip()
        if not 0 <= line_no < len(context) or not quote:
            continue
        located, strategy = _locate_quote(context, line_no, quote)
        logger.debug("ground: line %d quote %r -> %s %s", line_no, quote, strategy, located)
        for span in located:
            if span in seen:
                continue
            seen.add(span)
            resolved: dict[str, Any] = {"line": span[0], "start": span[1], "end": span[2]}
            if "reason" in item:
                resolved["reason"] = item["reason"]
            spans.append(resolved)
    return sorted(spans, key=lambda s: (s["line"], s["start"]))
