from typing import Any

from ..parse import parse_groundings


def parse_suggestions(response: str, include_reason: bool) -> list[dict[str, Any]]:
    """Like parse_groundings, but keeps a non-blank string "reason" when include_reason is set
    and strips it otherwise."""
    items = []
    for item in parse_groundings(response):
        entry = {"line": item["line"], "quote": item["quote"]}
        reason = item.get("reason")
        if include_reason and isinstance(reason, str) and reason.strip():
            entry["reason"] = reason.strip()
        items.append(entry)
    return items
