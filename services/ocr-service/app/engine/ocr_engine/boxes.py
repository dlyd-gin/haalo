def estimate_box(line_bbox: list[int], line_text: str, start: int, end: int) -> list[int]:
    """The [start, end) chars of an OCR line as a slice of its bbox, by char position: full line
    height, x split evenly per char. Rough for proportional fonts, but always on the right line."""
    x1, y1, x2, y2 = line_bbox
    per_char = (x2 - x1) / max(len(line_text), 1)
    return [round(x1 + start * per_char), y1, round(x1 + end * per_char), y2]


def resolve_boxes(phrases: list[dict], located: list[list[int] | None]) -> list[dict]:
    """One {bbox, source} per phrase: the model's box ("located") when its vertical centre lies on
    the phrase's OCR line (padded by half the line height), else estimate_box ("estimated") — the
    model can miss a phrase or match the same words elsewhere in the image."""
    out = []
    for phrase, box in zip(phrases, located):
        lx1, ly1, lx2, ly2 = phrase["line_bbox"]
        pad = (ly2 - ly1) / 2
        if box is not None and ly1 - pad <= (box[1] + box[3]) / 2 <= ly2 + pad:
            out.append({"bbox": box, "source": "located"})
        else:
            out.append(
                {
                    "bbox": estimate_box(phrase["line_bbox"], phrase["line_text"], phrase["start"], phrase["end"]),
                    "source": "estimated",
                }
            )
    return out
