from fastapi import HTTPException

from .engine.ocr_engine import OcrEngine

# Set by the lifespan in main.py. Read this via get_engine() (or `state.engine`) at request
# time — never `from .state import engine`, which would capture the value at import.
engine: OcrEngine | None = None


def get_engine() -> OcrEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return engine
