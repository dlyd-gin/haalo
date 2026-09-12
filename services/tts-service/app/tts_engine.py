import io
import struct
import time
from collections.abc import Iterator

import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model

# Mono, 16-bit PCM — matches the only subtype/channel layout this engine has ever written.
_CHANNELS = 1
_BITS_PER_SAMPLE = 16

# Streaming-WAV convention (used by tools like ffmpeg/arecord for live/unknown-length
# capture): declare the RIFF and data chunk sizes as "unspecified" so a canonical 44-byte
# header can be sent before the total length is known, ahead of any audio being generated.
_UNKNOWN_SIZE = 0xFFFFFFFF


def _streaming_wav_header(sample_rate: int) -> bytes:
    byte_rate = sample_rate * _CHANNELS * _BITS_PER_SAMPLE // 8
    block_align = _CHANNELS * _BITS_PER_SAMPLE // 8
    return (
        b"RIFF"
        + struct.pack("<I", _UNKNOWN_SIZE)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<IHHIIHH", 16, 1, _CHANNELS, sample_rate, byte_rate, block_align, _BITS_PER_SAMPLE)
        + b"data"
        + struct.pack("<I", _UNKNOWN_SIZE)
    )


class TtsEngine:
    """Wraps mlx-audio model loading and synthesis."""

    def __init__(self, model_path: str):
        self._model = load_model(model_path)

    def synthesize_wav_stream(self, text: str, voice: str) -> Iterator[bytes]:
        started_at = time.monotonic()

        sample_rate = getattr(self._model, "sample_rate", None)
        if sample_rate is None:
            raise RuntimeError("tts model does not expose a sample_rate")
        yield _streaming_wav_header(sample_rate)

        # generate()'s own EOS check normally stops it well under this, but when
        # EOS sampling doesn't trigger there's no other safety net — it silently
        # runs the library's full max_tokens default (4096 steps x 16 forward
        # passes each), which can take tens of minutes for a short phrase. Scale
        # the cap to input length so a stuck/non-terminating generation is bounded
        # by what's actually being spoken instead of a flat worst case.
        max_tokens = min(4096, max(200, len(text) * 4))

        chunk_count = 0
        for result in self._model.generate(
            text=text,
            voice=voice,
            stream=True,
            streaming_interval=0.32,
            max_tokens=max_tokens,
        ):
            chunk_count += 1
            buffer = io.BytesIO()
            sf.write(buffer, np.asarray(result.audio), sample_rate, format="RAW", subtype="PCM_16")
            yield buffer.getvalue()

        if chunk_count == 0:
            raise RuntimeError("mlx-audio produced no audio for the given text")

        print(
            f"[tts-engine] generate={time.monotonic() - started_at:.2f}s chunks={chunk_count}"
        )
