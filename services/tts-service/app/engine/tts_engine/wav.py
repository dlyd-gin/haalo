import struct

# Mono, 16-bit PCM — matches the only subtype/channel layout this engine has ever written.
_CHANNELS = 1
_BITS_PER_SAMPLE = 16

# Streaming-WAV convention (used by tools like ffmpeg/arecord for live/unknown-length
# capture): declare the RIFF and data chunk sizes as "unspecified" so a canonical 44-byte
# header can be sent before the total length is known, ahead of any audio being generated.
_UNKNOWN_SIZE = 0xFFFFFFFF


def streaming_wav_header(sample_rate: int) -> bytes:
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
