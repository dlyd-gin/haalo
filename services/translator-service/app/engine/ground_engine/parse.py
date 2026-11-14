import json
import re
from typing import Any

# Qwen3 may prefix its reply with a <think>...</think> block even when thinking is disabled.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def parse_groundings(response: str) -> list[dict[str, Any]]:
    """Extract the model's JSON array of {line, quote} items; anything malformed yields []."""
    response = THINK_BLOCK.sub("", response)
    match = JSON_ARRAY.search(response)
    if match is None:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return [
        item
        for item in map(_coerce_line, items)
        if isinstance(item, dict)
        and isinstance(item.get("line"), int)
        and not isinstance(item.get("line"), bool)
        and isinstance(item.get("quote"), str)
    ]


def _coerce_line(item: Any) -> Any:
    """The item with a digit-string "line" ("14", as the model sometimes writes it) turned into an int."""
    if isinstance(item, dict) and isinstance(item.get("line"), str) and item["line"].strip().isdigit():
        return {**item, "line": int(item["line"].strip())}
    return item
