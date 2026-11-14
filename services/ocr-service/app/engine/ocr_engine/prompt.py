PROMPT = (
    "Read all the text in this image. Return ONLY a JSON array, one object per visual line of text, "
    "in reading order. Each object has the form "
    '{"text": "<the line, transcribed verbatim>", "bbox_2d": [x1, y1, x2, y2]} '
    "where bbox_2d is the line's bounding box with coordinates normalized to 0-1000 "
    "(top-left origin). No commentary, no markdown."
)


def locate_prompt(phrases: list[str]) -> str:
    """Ask for the box of each numbered phrase; the reply is parsed by parse_located."""
    listed = "\n".join(f"{i}: {phrase}" for i, phrase in enumerate(phrases))
    return (
        "Find each of these phrases in the image:\n"
        f"{listed}\n"
        "Return ONLY a JSON array with one object per phrase you find, of the form "
        '{"id": <the phrase number>, "bbox_2d": [x1, y1, x2, y2]} '
        "where bbox_2d tightly bounds just that phrase, with coordinates normalized to 0-1000 "
        "(top-left origin). Leave out phrases you cannot find. No commentary, no markdown."
    )
