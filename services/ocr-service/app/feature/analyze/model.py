from pydantic import BaseModel


class OcrLine(BaseModel):
    text: str
    bbox: list[int]  # [x1, y1, x2, y2] in pixels, top-left origin
