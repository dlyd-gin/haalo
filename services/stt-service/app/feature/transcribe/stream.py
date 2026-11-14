import asyncio
import threading
from typing import AsyncIterator

from ...engine.stt_engine import SttEngine


def stream_transcript_events(
    engine: SttEngine, audio_bytes: bytes, language: str
) -> AsyncIterator[dict]:
    """Bridge the engine's blocking generator (mlx-audio decoding is CPU/GPU-bound) onto
    the event loop: a worker thread drives the generator and pushes events into an
    asyncio.Queue via call_soon_threadsafe, and this async generator just drains that
    queue. Mirrors translator-service's stream_translate_events."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def worker() -> None:
        try:
            accumulated_text = ""
            language_detected = language
            for result in engine.transcribe_stream(audio_bytes, language):
                accumulated_text += result["text"]
                language_detected = result["language"] or language_detected
                if result["is_final"]:
                    loop.call_soon_threadsafe(
                        queue.put_nowait,
                        {"type": "done", "text": accumulated_text, "language": language_detected},
                    )
                else:
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"type": "delta", "text": result["text"]}
                    )
        except Exception as exc:  # noqa: BLE001 - relay any engine failure to the client
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator() -> AsyncIterator[dict]:
        while True:
            event = await queue.get()
            if event is sentinel:
                break
            yield event

    return event_generator()
