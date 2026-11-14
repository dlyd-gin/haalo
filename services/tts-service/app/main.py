from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import state
from .config import MODEL_PATH
from .engine.tts_engine import TtsEngine
from .feature import synthesize


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[tts-service] loading model from {MODEL_PATH} ...")
    state.engine = TtsEngine(MODEL_PATH)
    print("[tts-service] model loaded")
    yield
    state.engine = None


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": state.engine is not None}


app.include_router(synthesize.router)
