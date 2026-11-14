import os

HOST = os.environ.get("DOC_HOST", "127.0.0.1")
PORT = int(os.environ.get("DOC_PORT", "8003"))  # 8003: next free port after tts(8000)/translator(8001)/stt(8002)
MARGIN_RATIO = float(os.environ.get("DOC_MARGIN_RATIO", "0.1"))  # top/bottom 10% of page height
LOG_LEVEL = os.environ.get("DOC_LOG_LEVEL", "INFO")
BATCH_SIZE = int(os.environ.get("DOC_BATCH_SIZE", "4"))  # max pages parsed concurrently per /extract-text request
GAP_SEPARATOR = os.environ.get("DOC_GAP_SEPARATOR", "    ")  # joiner for widely separated segments on one line
GAP_FACTOR = float(
    os.environ.get("DOC_GAP_FACTOR", "2.5")
)  # horizontal gap, as a multiple of word height, above which two words count as separate segments
X_TOLERANCE_RATIO_FALLBACK =float(
    os.environ.get("DOC_X_TOLERANCE_RATIO_FALLBACK", "0.2")
)  # used only when a page has too few characters to auto-calibrate its own word-gap threshold
ANNOTATE_DPI = int(os.environ.get("DOC_ANNOTATE_DPI", "100"))  # render resolution of /annotate-images JPEGs
TRANSLATOR_URL = os.environ.get("DOC_TRANSLATOR_URL", "http://127.0.0.1:8001").rstrip("/")  # translator-service, used by /ground-state
GROUND_TIMEOUT = float(os.environ.get("DOC_GROUND_TIMEOUT", "120"))  # seconds to wait for the LLM to ground a state
SUMMARY_TIMEOUT = float(os.environ.get("DOC_SUMMARY_TIMEOUT", "120"))  # seconds to wait for the LLM to summarize suggestions
HIGHLIGHT_COLOR = os.environ.get("DOC_HIGHLIGHT_COLOR", "YELLOW").upper()  # a docx WD_COLOR_INDEX name
PDF_HIGHLIGHT_COLOR = os.environ.get("DOC_PDF_HIGHLIGHT_COLOR", "ffff00")  # hex RGB of /giveme-suggestion-pdf highlight annotations
OCR_URL = os.environ.get("DOC_OCR_URL", "http://127.0.0.1:8004").rstrip("/")  # ocr-service, used by /image-to-words
OCR_TIMEOUT = float(os.environ.get("DOC_OCR_TIMEOUT", "300"))  # seconds to wait for the VLM to read an image
OCR_TABLE_ROWS_MAX = int(
    os.environ.get("DOC_OCR_TABLE_ROWS_MAX", "60")
)  # table rows read by their own ocr call per image; rows past it keep the page ocr's (less accurate) text
OCR_TABLE_CELLS_MAX = int(
    os.environ.get("DOC_OCR_TABLE_CELLS_MAX", "40")
)  # cells read alone per image, when their row's read didn't give one line per cell
