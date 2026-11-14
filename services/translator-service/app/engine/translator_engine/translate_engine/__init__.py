from collections.abc import Iterator

from ..generate import generate_answer, stream_answer
from .system_prompt import build_system_prompt


class TranslateEngine:
    """Translates text between SUPPORTED_LANGUAGES with the loaded chat-tuned LLM."""

    def __init__(self, model, tokenizer):
        self._model = model
        self._tokenizer = tokenizer

    def translate(self, text: str, source_language: str, target_language: str) -> tuple[str, str]:
        return generate_answer(
            self._model, self._tokenizer, build_system_prompt(source_language, target_language), text
        )

    def translate_stream(self, text: str, source_language: str, target_language: str) -> Iterator[str]:
        return stream_answer(
            self._model, self._tokenizer, build_system_prompt(source_language, target_language), text
        )
