import os

MODEL_PATH = os.environ.get("TRANSLATOR_MODEL_PATH", "./models/Qwen3-8B-4bit")
HOST = os.environ.get("TRANSLATOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("TRANSLATOR_PORT", "8001"))  # 8001: distinct from tts-service's 8000

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "jp": "Japanese",
    "zh": "Mandarin Chinese",
    "ko": "Korean",
}
