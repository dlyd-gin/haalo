from fastapi import HTTPException

from .engine.ground_engine.giveme_suggestion_engine import GivemeSuggestionEngine
from .engine.ground_engine.ground_state_engine import GroundStateEngine
from .engine.ground_engine.summarize_suggestion_engine import SummarizeSuggestionEngine
from .engine.translator_engine import TranslatorEngine

# Set by the lifespan in main.py. Read these via the getters (or `state.engine`) at request
# time — never `from .state import engine`, which would capture the value at import.
engine: TranslatorEngine | None = None
ground_state_engine: GroundStateEngine | None = None
giveme_suggestion_engine: GivemeSuggestionEngine | None = None
summarize_suggestion_engine: SummarizeSuggestionEngine | None = None


def get_engine() -> TranslatorEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return engine


def get_ground_state_engine() -> GroundStateEngine:
    if ground_state_engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return ground_state_engine


def get_giveme_suggestion_engine() -> GivemeSuggestionEngine:
    if giveme_suggestion_engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return giveme_suggestion_engine


def get_summarize_suggestion_engine() -> SummarizeSuggestionEngine:
    if summarize_suggestion_engine is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")
    return summarize_suggestion_engine
