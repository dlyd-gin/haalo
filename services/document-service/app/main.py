import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import LOG_LEVEL
from .feature import (
    analyze,
    annotate_images,
    extract_images,
    extract_markdown,
    extract_tables,
    extract_text,
    extract_words,
    giveme_suggestion,
    giveme_suggestion_image,
    giveme_suggestion_pdf,
    ground_state,
    image_to_words,
)

# uvicorn's --log-level flag only configures uvicorn's own loggers, not application loggers,
# so debug logging here needs its own setup (DOC_LOG_LEVEL env var, default INFO).
logging.basicConfig(level=LOG_LEVEL)
# pdfplumber/pdfminer log every parsed PDF token at DEBUG, which drowns out our own messages.
logging.getLogger("pdfminer").setLevel(logging.WARNING)

app = FastAPI()


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(analyze.router)
app.include_router(extract_text.router)
app.include_router(extract_tables.router)
app.include_router(extract_images.router)
app.include_router(annotate_images.router)
app.include_router(extract_markdown.router)
app.include_router(extract_words.router)
app.include_router(image_to_words.router)
app.include_router(ground_state.router)
app.include_router(giveme_suggestion.router)
app.include_router(giveme_suggestion_pdf.router)
app.include_router(giveme_suggestion_image.router)
