from pydantic import BaseModel


class TranslateRequest(BaseModel):
    text: str
    source_language: str
    target_language: str
