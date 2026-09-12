import io
import time
from collections.abc import Iterator

import mlx_whisper
from mlx_audio.stt.utils import SAMPLE_RATE, load_audio, load_model

# Any local dir or hf repo id for the whisper-large-v3-turbo family (including the -4bit
# variant) routes through mlx-whisper instead of mlx-audio's Qwen3-ASR path.
WHISPER_MODEL_MARKER = "whisper-large-v3-turbo"


class SttEngine:
    """Wraps mlx-audio / mlx-whisper STT model loading and streaming transcription."""

    def __init__(self, model_path: str):
        self._model_path = model_path
        self._is_whisper = WHISPER_MODEL_MARKER in model_path
        if not self._is_whisper:
            self._model = load_model(model_path)

    def transcribe_stream(self, audio_bytes: bytes, language: str) -> Iterator[dict]:
        started_at = time.monotonic()

        # audio_io.read() (called via load_audio) auto-detects WebM/Opus/M4A from the
        # BytesIO's magic bytes and shells out to ffmpeg to decode them — everything a
        # browser MediaRecorder can produce.
        audio = load_audio(io.BytesIO(audio_bytes), sr=SAMPLE_RATE)

        if self._is_whisper:
            yield from self._transcribe_stream_whisper(audio, language, started_at)
            return

        chunk_count = 0
        for result in self._model.generate(audio, stream=True, language=language):
            chunk_count += 1
            yield {"text": result.text, "is_final": result.is_final, "language": result.language}

        if chunk_count == 0:
            raise RuntimeError("mlx-audio produced no transcription for the given audio")

        print(
            f"[stt-engine] transcribe={time.monotonic() - started_at:.2f}s chunks={chunk_count}"
        )

    def _transcribe_stream_whisper(self, audio, language: str, started_at: float) -> Iterator[dict]:
        # mlx-whisper's transcribe() is a single blocking call with no incremental decode
        # hook — it re-resolves path_or_hf_repo (local dir or hf repo id) on every call.
        result = mlx_whisper.transcribe(audio, path_or_hf_repo=self._model_path, language=language)
        detected_language = result.get("language") or language
        segments = result.get("segments") or []

        if not segments:
            raise RuntimeError("mlx-whisper produced no transcription for the given audio")

        # Segments are already fully decoded by the time transcribe() returns, but yielding
        # them one at a time keeps the same delta/done wire shape main.py expects.
        for segment in segments:
            yield {"text": segment["text"], "is_final": False, "language": detected_language}
        yield {"text": "", "is_final": True, "language": detected_language}

        print(
            f"[stt-engine] transcribe(whisper)={time.monotonic() - started_at:.2f}s "
            f"segments={len(segments)}"
        )
