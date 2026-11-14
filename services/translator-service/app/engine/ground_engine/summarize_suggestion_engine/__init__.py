import logging

from .system_prompt import SUMMARIZE_SYSTEM_PROMPT
from .user_prompt import build_summarize_prompt

logger = logging.getLogger(__name__)


class SummarizeSuggestionEngine:
    """Writes a short answer to an intent from the document items /giveme-suggestion picked."""

    def __init__(self, model, tokenizer):
        self._model = model
        self._tokenizer = tokenizer

    def summarize(self, intent: str, highlights: list[str]) -> str:
        from ...translator_engine.generate import generate_answer  # lazy: keeps the prompt helpers importable without MLX

        user_text = build_summarize_prompt(intent, highlights)
        logger.debug("summarize: prompt:\n%s", user_text)
        _, summary = generate_answer(self._model, self._tokenizer, SUMMARIZE_SYSTEM_PROMPT, user_text)
        return summary
