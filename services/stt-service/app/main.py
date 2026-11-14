from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import state
from .config import MODEL_PATH
from .engine.stt_engine import SttEngine
from .feature import transcribe


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[stt-service] loading model from {MODEL_PATH} ...")
    state.engine = SttEngine(MODEL_PATH)
    print("[stt-service] model loaded")
    yield
    state.engine = None


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": state.engine is not None}


app.include_router(transcribe.router)
