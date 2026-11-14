import json
import re

# Qwen3.x may prefix its reply with a <think>...</think> block; drop it.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
CODE_FENCE = re.compile(r"```(?:json)?")
# One flat {...} object per match — lets us salvage complete entries from truncated output.
OBJECT = re.compile(r"\{[^{}]*\}")


def parse_lines(raw: str, width: int, height: int) -> list[dict]:
    """Turn the model's raw reply into [{"text", "bbox": [x1, y1, x2, y2]}] in pixel coordinates.

    Tolerates code fences and truncated output (complete objects are kept, the broken tail is
    dropped); entries without text or a usable bbox are skipped."""
    cleaned = CODE_FENCE.sub("", THINK_BLOCK.sub("", raw)).strip()
    lines: list[dict] = []
    for match in OBJECT.finditer(cleaned):
        try:
            item = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        text = item.get("text")
        box = item.get("bbox_2d")
        if not isinstance(text, str) or not text.strip():
            continue
        if not _is_box(box):
            continue
        lines.append({"text": text.strip(), "bbox": _to_pixels(box, width, height)})
    return lines


def parse_located(raw: str, count: int, width: int, height: int) -> list[list[int] | None]:
    """Turn the model's reply to locate_prompt into one pixel bbox (or None) per phrase id 0..count-1.

    Same tolerance as parse_lines; an unknown id, a malformed or empty box is ignored, and the first
    usable box wins when an id repeats."""
    cleaned = CODE_FENCE.sub("", THINK_BLOCK.sub("", raw)).strip()
    boxes: list[list[int] | None] = [None] * count
    for match in OBJECT.finditer(cleaned):
        try:
            item = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        index = item.get("id")
        box = item.get("bbox_2d")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < count or boxes[index]:
            continue
        if not _is_box(box):
            continue
        pixels = _to_pixels(box, width, height)
        if pixels[0] < pixels[2] and pixels[1] < pixels[3]:
            boxes[index] = pixels
    return boxes


def _is_box(box) -> bool:
    return isinstance(box, list) and len(box) == 4 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in box
    )


def _to_pixels(box: list[float], width: int, height: int) -> list[int]:
    """A 0-1000 normalized [x1, y1, x2, y2] as image pixels, clamped to the image and ordered."""
    x1, y1, x2, y2 = box
    pixels = [
        _clamp(round(x1 / 1000 * width), width),
        _clamp(round(y1 / 1000 * height), height),
        _clamp(round(x2 / 1000 * width), width),
        _clamp(round(y2 / 1000 * height), height),
    ]
    if pixels[0] > pixels[2]:
        pixels[0], pixels[2] = pixels[2], pixels[0]
    if pixels[1] > pixels[3]:
        pixels[1], pixels[3] = pixels[3], pixels[1]
    return pixels


def _clamp(value: int, upper: int) -> int:
    return max(0, min(value, upper))
