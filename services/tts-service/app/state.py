import anyio
from fastapi import HTTPException

from .engine.tts_engine import TtsEngine

# Set by the lifespan in main.py. Read this via get_engine() (or `state.engine`) at request
# time — never `from .state import engine`, which would capture the value at import.
engine: TtsEngine | None = None

# The shared model instance keeps mutable streaming-decoder state on itself
# (reset at the start of every generate() call). run_in_threadpool dispatches
# onto a real multi-threaded executor, so without this lock two overlapping
# requests can race on that shared state and corrupt each other's output.
engine_lock = anyio.Lock()


def get_engine() -> TtsEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return engine
