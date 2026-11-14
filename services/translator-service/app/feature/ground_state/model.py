from pydantic import BaseModel


class GroundRequest(BaseModel):
    state: str
    context: list[str]


class Grounding(BaseModel):
    line: int  # index into the request's context list
    start: int  # char offset within that line, inclusive
    end: int  # char offset within that line, exclusive


class GroundResponse(BaseModel):
    groundings: list[Grounding]
