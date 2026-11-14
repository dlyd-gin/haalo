import asyncio
import threading
from typing import AsyncIterator

from ...engine.translator_engine import TranslatorEngine


def stream_translate_events(
    engine: TranslatorEngine, text: str, source_language: str, target_language: str
) -> AsyncIterator[dict[str, str]]:
    """Bridge the engine's blocking generator (MLX generation is CPU/GPU-bound) onto the
    event loop: a worker thread drives the generator and pushes events into an asyncio.Queue
    via call_soon_threadsafe, and this async generator just drains that queue."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel = object()

    def worker() -> None:
        try:
            for event in engine.translate_stream(text, source_language, target_language):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:  # noqa: BLE001 - relay any engine failure to the client
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        while True:
            event = await queue.get()
            if event is sentinel:
                break
            yield event

    return event_generator()
