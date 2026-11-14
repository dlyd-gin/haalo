import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import state
from .config import LOG_LEVEL, MODEL_PATH
from .engine.ocr_engine import OcrEngine
from .feature import analyze, highlight

# uvicorn's --log-level only configures uvicorn's own loggers, so app logging needs its own setup.
logging.basicConfig(level=LOG_LEVEL)
logging.getLogger("PIL").setLevel(logging.INFO)  # its DEBUG is one PNG chunk dump per image read


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[ocr-service] loading model from {MODEL_PATH} ...")
    state.engine = OcrEngine(MODEL_PATH)
    print("[ocr-service] model loaded")
    yield
    state.engine = None


app = FastAPI(lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": state.engine is not None}


app.include_router(analyze.router)
app.include_router(highlight.router)
