from pydantic import BaseModel


class SummarizeRequest(BaseModel):
    intent: str
    highlights: list[str]  # the highlighted spans /giveme-suggestion picked, in document order


class SummarizeResponse(BaseModel):
    summary: str
