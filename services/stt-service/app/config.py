import os

MODEL_PATH = os.environ.get("STT_MODEL_PATH", "./models/whisper-large-v3-turbo")
HOST = os.environ.get("STT_HOST", "127.0.0.1")
PORT = int(os.environ.get("STT_PORT", "8002"))  # 8002: next free port after tts(8000)/translator(8001)

# Canonical app codes (language-catalog.ts) -> names Qwen3-ASR's `support_languages`
# expects. Unvalidated — same "Known risk" caveat as tts-service's LANGUAGE_VOICE_MAP.
LANGUAGE_MAP: dict[str, str] = {
    "en": "english",
    "ja": "japanese",
    "zh": "chinese",
    "ko": "korean",
}
