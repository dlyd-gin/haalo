from collections.abc import Iterator

from mlx_lm import load

from .rephrase_engine import RephraseEngine
from .translate_engine import TranslateEngine


class TranslatorEngine:
    """Wraps mlx-lm model loading and runs rephrase → translate on the chat-tuned LLM."""

    def __init__(self, model_path: str):
        self._model, self._tokenizer = load(model_path)
        self._rephrase = RephraseEngine(self._model, self._tokenizer)
        self._translate = TranslateEngine(self._model, self._tokenizer)

    @property
    def model(self):
        return self._model

    @property
    def tokenizer(self):
        return self._tokenizer

    def translate(self, text: str, source_language: str, target_language: str) -> tuple[str, str, str]:
        # Step 1: rephrase the raw user input for grammar/clarity before translating it.
        rephrased_text = self._rephrase.rephrase(text)

        # Step 2: run the existing translation prompt against the rephrased text.
        thinking, answer = self._translate.translate(rephrased_text, source_language, target_language)
        return thinking, answer, rephrased_text

    def translate_stream(
        self, text: str, source_language: str, target_language: str
    ) -> Iterator[dict[str, str]]:
        # Step 1: rephrase the raw user input for grammar/clarity before translating it (blocking —
        # this pass isn't shown to the user, only the translation pass below streams).
        rephrased_text = self._rephrase.rephrase(text)

        # Step 2: stream the translation prompt against the rephrased text.
        answer_parts: list[str] = []
        for delta in self._translate.translate_stream(rephrased_text, source_language, target_language):
            answer_parts.append(delta)
            yield {"type": "delta", "text": delta}

        yield {"type": "done", "answer": "".join(answer_parts), "rephrased_text": rephrased_text}
