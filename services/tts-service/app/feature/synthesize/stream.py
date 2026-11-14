import asyncio
import threading
from typing import AsyncIterator

from ...engine.tts_engine import TtsEngine


def stream_wav_chunks(engine: TtsEngine, text: str, voice: str) -> AsyncIterator[bytes]:
    """Bridge the engine's blocking generator (mlx-audio generation is CPU/GPU-bound) onto
    the event loop: a worker thread drives the generator and pushes chunks into an
    asyncio.Queue via call_soon_threadsafe, and this async generator just drains that queue.
    A failure mid-stream is logged and simply ends the stream early (no JSON error envelope
    is possible on a raw audio/wav body) — the client sees a truncated download."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def worker() -> None:
        try:
            for chunk in engine.synthesize_wav_stream(text, voice):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
        except Exception as exc:  # noqa: BLE001 - can't relay this into an audio/wav body
            print(f"[tts-service] streaming synthesis failed: {exc}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def iterator() -> AsyncIterator[bytes]:
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield item

    return iterator()
