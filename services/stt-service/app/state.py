import anyio
from fastapi import HTTPException

from .engine.stt_engine import SttEngine

# Set by the lifespan in main.py. Read this via get_engine() (or `state.engine`) at request
# time — never `from .state import engine`, which would capture the value at import.
engine: SttEngine | None = None

# The shared model instance keeps mutable streaming-decoder state on itself, just like
# tts-service's TtsEngine — serialize concurrent requests against it.
engine_lock = anyio.Lock()


def get_engine() -> SttEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return engine
