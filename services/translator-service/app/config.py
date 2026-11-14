import os

MODEL_PATH = os.environ.get("TRANSLATOR_MODEL_PATH", "./models/Qwen3-8B-4bit")
HOST = os.environ.get("TRANSLATOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("TRANSLATOR_PORT", "8001"))  # 8001: distinct from tts-service's 8000

LOG_LEVEL = os.environ.get("TRANSLATOR_LOG_LEVEL", "INFO").upper()  # DEBUG logs /ground-state prompts, raw model output and resolved spans
GROUND_MAX_TOKENS = int(os.environ.get("TRANSLATOR_GROUND_MAX_TOKENS", "512"))  # cap on /ground-state JSON output

GIVEME_MAX_TOKENS = int(os.environ.get("TRANSLATOR_GIVEME_MAX_TOKENS", "8192"))  # cap on /giveme-suggestion JSON output (reasons add length)
# /giveme-suggestion runs Qwen3 in thinking mode, which must not decode greedily (the model card warns it
# degrades and loops: "let me check line 39 again" until it gives up). top_p/top_k are the card's settings;
# temperature is lowered from its 0.6 so the same menu and intent pick the same items from run to run.
GIVEME_TEMPERATURE = float(os.environ.get("TRANSLATOR_GIVEME_TEMPERATURE", "0.4"))
GIVEME_TOP_P = float(os.environ.get("TRANSLATOR_GIVEME_TOP_P", "0.95"))
GIVEME_TOP_K = int(os.environ.get("TRANSLATOR_GIVEME_TOP_K", "20"))
GIVEME_INTENT_MAX_TOKENS = int(os.environ.get("TRANSLATOR_GIVEME_INTENT_MAX_TOKENS", "64"))  # cap on the intent rewrite

SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "jp": "Japanese",
    "zh": "Mandarin Chinese",
    "ko": "Korean",
}
