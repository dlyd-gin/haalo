import os

# Supported OCR models (directory names under ./models). Switch with OCR_MODEL=<name>.
OCR_MODELS = (
    "Qwen3-VL-8B-Instruct-4bit",  # default: best of the three
    "Qwen3.5-4B-MLX-8bit",
    "NuExtract3-mlx-8bits",
)
DEFAULT_OCR_MODEL = OCR_MODELS[0]

OCR_MODEL = os.environ.get("OCR_MODEL", DEFAULT_OCR_MODEL)
if OCR_MODEL not in OCR_MODELS:
    raise ValueError(f"OCR_MODEL={OCR_MODEL!r} is not supported; choose one of: {', '.join(OCR_MODELS)}")

MODEL_PATH = os.environ.get("OCR_MODEL_PATH", f"./models/{OCR_MODEL}")  # explicit path still overrides (unvalidated)
HOST = os.environ.get("OCR_HOST", "127.0.0.1")
PORT = int(os.environ.get("OCR_PORT", "8004"))  # 8004: next free port after tts(8000)/translator(8001)/stt(8002)/document(8003)

LOG_LEVEL = os.environ.get("OCR_LOG_LEVEL", "INFO").upper()  # DEBUG logs the raw model output and parsed lines
MAX_TOKENS = int(os.environ.get("OCR_MAX_TOKENS", "8192"))  # cap on the JSON line list the model emits
MAX_IMAGE_BYTES = int(os.environ.get("OCR_MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))  # request body limit
MIN_LONG_SIDE = int(os.environ.get("OCR_MIN_LONG_SIDE", "1600"))  # smaller images are upscaled first: more vision tokens per glyph, fewer skipped lines (0 = off)
HIGHLIGHT_COLOR = tuple(
    int(v) for v in os.environ.get("OCR_HIGHLIGHT_COLOR", "255,230,0,110").split(",")
)  # RGBA fill /highlight lays over each phrase (alpha 0-255)
HIGHLIGHT_LOCATE = os.environ.get("OCR_HIGHLIGHT_LOCATE", "1") != "0"  # 0 = skip the model call, estimate every box from its OCR line
CONTINUE_MAX = int(os.environ.get("OCR_CONTINUE_MAX", "3"))  # extra /analyze passes below where the model stopped reading a tall image (0 = off)
CONTINUE_MIN_RATIO = float(os.environ.get("OCR_CONTINUE_MIN_RATIO", "0.1"))  # continue only while the unread bottom is taller than this share of the image
