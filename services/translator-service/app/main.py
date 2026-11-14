import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import state
from .config import LOG_LEVEL, MODEL_PATH
from .engine.ground_engine.giveme_suggestion_engine import GivemeSuggestionEngine
from .engine.ground_engine.ground_state_engine import GroundStateEngine
from .engine.ground_engine.summarize_suggestion_engine import SummarizeSuggestionEngine
from .engine.translator_engine import TranslatorEngine
from .feature import giveme_suggestion, ground_state, summarize_suggestion, translate

# uvicorn's --log-level only configures uvicorn's own loggers, so app logging needs its own setup.
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[translator-service] loading model from {MODEL_PATH} ...")
    state.engine = TranslatorEngine(MODEL_PATH)
    # all share the translator's loaded weights
    state.ground_state_engine = GroundStateEngine(state.engine.model, state.engine.tokenizer)
    state.giveme_suggestion_engine = GivemeSuggestionEngine(state.engine.model, state.engine.tokenizer)
    state.summarize_suggestion_engine = SummarizeSuggestionEngine(state.engine.model, state.engine.tokenizer)
    print("[translator-service] model loaded")
    yield
    state.engine = None
    state.ground_state_engine = None
    state.giveme_suggestion_engine = None
    state.summarize_suggestion_engine = None


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": state.engine is not None}


app.include_router(translate.router)
app.include_router(ground_state.router)
app.include_router(giveme_suggestion.router)
app.include_router(summarize_suggestion.router)
