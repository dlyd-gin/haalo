from pydantic import BaseModel


class GivemeRequest(BaseModel):
    context: list[str]
    intent: str
    include_reason: bool = False  # annotate each suggestion with a short reason


class Suggestion(BaseModel):
    line: int  # index into the request's context list
    start: int  # char offset within that line, inclusive
    end: int  # char offset within that line, exclusive
    reason: str | None = None  # only set when include_reason is true


class GivemeResponse(BaseModel):
    suggestions: list[Suggestion]
