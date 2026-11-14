import io

from PIL import Image, ImageDraw


def draw_highlights(data: bytes, boxes: list[list[int]], color: tuple[int, ...]) -> bytes:
    """The image as PNG with a translucent `color` (RGBA) fill over each [x1, y1, x2, y2] pixel box."""
    with Image.open(io.BytesIO(data)) as image:
        base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for box in boxes:
        draw.rectangle(box, fill=color)
    out = io.BytesIO()
    Image.alpha_composite(base, overlay).convert("RGB").save(out, format="PNG")
    return out.getvalue()
