from pydantic import BaseModel, model_validator


class Phrase(BaseModel):
    line_text: str
    line_bbox: list[int]  # [x1, y1, x2, y2] of the OCR line, in pixels, top-left origin
    start: int  # [start, end) chars of line_text to highlight
    end: int

    @model_validator(mode="after")
    def _check(self):
        if len(self.line_bbox) != 4:
            raise ValueError("line_bbox must have 4 values")
        if not 0 <= self.start < self.end <= len(self.line_text):
            raise ValueError("start/end must be a non-empty range of line_text")
        return self

    @property
    def text(self) -> str:
        return self.line_text[self.start : self.end]
