import logging
import re

from .layout import group_lines

logger = logging.getLogger(__name__)

_DIGITS_RE = re.compile(r"^\d+$")
_ROMAN_RE = re.compile(
    r"(?=[mdclxvi])m{0,4}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})", re.IGNORECASE
)


# A bare digit/roman-numeral candidate (no "page" label) is only trusted as a page number when
# its line has at most this many words — otherwise it's more likely a number embedded in running
# prose (e.g. a wrapped header/title like "...over the 10 Year capital...") than a page number.
_MAX_BARE_CANDIDATE_LINE_WORDS = 3

# Standard document-structure reference words (and their common abbreviations) that can precede
# a page reference, e.g. "Schedule B - Page 4", "Exhibit A, Page 2", "Table 3 - Page 12". Not an
# exhaustive list of every possible label, but covers the conventions found across legal,
# technical, and regulatory documents rather than just one example like "Annex".
_SECTION_LABELS = (
    r"annex(?:ure)?|appendi(?:x|ces)|app|"
    r"schedule|sched|"
    r"exhibit|"
    r"attachment|att|"
    r"enclosure|encl|"
    r"addendum|"
    r"supplement|supp|"
    r"section|sec|"
    r"chapter|ch|"
    r"article|art|"
    r"paragraph|para|"
    r"clause|"
    r"part|"
    r"tab|"
    r"volume|vol|"
    r"module|"
    r"unit|"
    r"table|"
    r"figure|fig"
)
_CONNECTOR = r"(?:of|-|–|—|,|:)"
_NUMERAL = r"[ivxlcdm]+|\d+"

# Matches an optional leading section label (e.g. "Annex 1") joined by a connector ("of", "-",
# ",", ":", or just whitespace) to a "Page N" reference, with an optional trailing "of TOTAL"
# fraction. Covers "Page 3 of 45", "Annex 1 - Page 3", "Annex 1 of Page 1", and plain "Page 12".
_PAGE_CONTEXT_RE = re.compile(
    rf"\b(?:(?P<section_label>{_SECTION_LABELS})\b\.?\s*"
    rf"(?P<section_num>[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)\s*{_CONNECTOR}?\s*)?"
    rf"\bpage\b\s*[:.,]?\s*(?P<page_num>{_NUMERAL})"
    rf"(?:\s*(?:of|/)\s*(?P<total>{_NUMERAL}))?",
    re.IGNORECASE,
)


def _is_page_number_token(text: str) -> bool:
    return bool(_DIGITS_RE.match(text)) or bool(_ROMAN_RE.fullmatch(text))


def _zone(word: dict, page_width: float) -> str:
    center_x = (word["x0"] + word["x1"]) / 2
    if center_x > page_width * 2 / 3:
        return "right"
    if center_x < page_width / 3:
        return "left"
    return "center"


def _log_lines(lines: list[list[dict]], band: str) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    for line in lines:
        logger.debug(
            "%s: line %r top=%.1f-%.1f words=%s",
            band,
            " ".join(w["text"] for w in line),
            min(w["top"] for w in line),
            max(w["bottom"] for w in line),
            [w["text"] for w in line],
        )


def _labeled_page_matches(lines: list[list[dict]], band: str) -> list[dict]:
    """Find "Page N" references (optionally with a section label and/or "of TOTAL") on any
    line, returning the full matched phrase alongside position info for tie-breaking."""
    matches = []
    for line in lines:
        line_text = " ".join(w["text"] for w in line)
        for match in _PAGE_CONTEXT_RE.finditer(line_text):
            page_num = match.group("page_num")
            total = match.group("total")
            if not _is_page_number_token(page_num):
                logger.debug(
                    "%s: rejected match %r in line %r - invalid page_num %r",
                    band,
                    match.group(0),
                    line_text,
                    page_num,
                )
                continue
            if total and not _is_page_number_token(total):
                logger.debug(
                    "%s: rejected match %r in line %r - invalid total %r",
                    band,
                    match.group(0),
                    line_text,
                    total,
                )
                continue
            logger.debug("%s: accepted labeled match %r from line %r", band, match.group(0), line_text)
            matches.append({"text": match.group(0).strip(), "top": line[0]["top"], "x1": line[-1]["x1"]})
    return matches


def select_printed_page(
    words: list[dict], page_width: float, *, prefer_bottom: bool, band: str = ""
) -> str:
    lines = group_lines(words)
    _log_lines(lines, band)

    # A "Page N" reference (optionally with a section label like "Annex 1" and/or an "of TOTAL"
    # fraction) is a stronger signal than raw position and wins regardless of zone, including the
    # left third the zone rule ignores.
    labeled = _labeled_page_matches(lines, band)
    if labeled:
        if prefer_bottom:
            best = max(labeled, key=lambda m: (m["top"], m["x1"]))
        else:
            best = min(labeled, key=lambda m: (m["top"], -m["x1"]))
        logger.debug("%s: selected labeled match %r (of %d candidate(s))", band, best["text"], len(labeled))
        return best["text"]

    candidates = [
        w for line in lines if len(line) <= _MAX_BARE_CANDIDATE_LINE_WORDS for w in line if _is_page_number_token(w["text"])
    ]
    if logger.isEnabledFor(logging.DEBUG):
        skipped = [
            w["text"]
            for line in lines
            if len(line) > _MAX_BARE_CANDIDATE_LINE_WORDS
            for w in line
            if _is_page_number_token(w["text"])
        ]
        if skipped:
            logger.debug(
                "%s: ignored bare candidate(s) %s - line has more than %d word(s)",
                band,
                skipped,
                _MAX_BARE_CANDIDATE_LINE_WORDS,
            )
    if not candidates:
        logger.debug("%s: no page-number candidates found", band)
        return ""

    by_zone: dict[str, list[dict]] = {"right": [], "center": [], "left": []}
    for w in candidates:
        by_zone[_zone(w, page_width)].append(w)

    for zone in ("right", "center"):  # a left-only candidate is not treated as a page number
        zone_candidates = by_zone[zone]
        if not zone_candidates:
            continue
        # Tie-break toward the edge the band borders (bottom edge for a footer, top edge for
        # a header), then rightmost, among candidates in this zone.
        if prefer_bottom:
            best = max(zone_candidates, key=lambda w: (w["top"], w["x1"]))
        else:
            best = min(zone_candidates, key=lambda w: (w["top"], -w["x1"]))
        logger.debug("%s: %r matched via %s zone", band, best["text"], zone)
        return best["text"]
    logger.debug("%s: candidate(s) found but only in left zone - discarded", band)
    return ""
