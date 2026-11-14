import re
from typing import Any

ADDON_LINE = re.compile(r"^\+\s*[^\d\s+]")  # "+ BACON", "+CHORIZO"; not the "+10" price after it
FILLER_LINE = re.compile(r"^(\+?\s*\$?\d+(\.\d+)?|V|VG|GF|DF|N)$", re.IGNORECASE)  # price or dietary tag
SECTION_HEADER = re.compile(r"(\.\.\.|…)$")  # "A BIT MORE..."


def _addon_parent(context: list[str], line_no: int) -> int | None:
    """The dish an add-on line belongs to: the nearest preceding line that is not itself an
    add-on, a price or a dietary tag. None when that line is blank or a section header."""
    for i in range(line_no - 1, -1, -1):
        text = context[i].strip()
        if ADDON_LINE.match(text) or FILLER_LINE.match(text):
            continue
        if not text or SECTION_HEADER.search(text):
            return None
        return i
    return None


def extend_addon_parents(spans: list[dict[str, Any]], context: list[str]) -> list[dict[str, Any]]:
    """For every span on an add-on line, also highlight the whole dish the add-on belongs to.
    The add-on's optional "reason" is copied onto the dish span."""
    seen = {(s["line"], s["start"], s["end"]) for s in spans}
    extended = list(spans)
    for span in spans:
        if not ADDON_LINE.match(context[span["line"]].strip()):
            continue
        parent = _addon_parent(context, span["line"])
        if parent is None:
            continue
        key = (parent, 0, len(context[parent]))
        if key in seen:
            continue
        seen.add(key)
        resolved: dict[str, Any] = {"line": key[0], "start": key[1], "end": key[2]}
        if "reason" in span:
            resolved["reason"] = span["reason"]
        extended.append(resolved)
    return sorted(extended, key=lambda s: (s["line"], s["start"]))
