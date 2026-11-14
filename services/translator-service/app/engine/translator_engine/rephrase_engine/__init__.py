from ..generate import generate_answer
from .system_prompt import REPHRASE_SYSTEM_PROMPT


class RephraseEngine:
    """Rewrites raw user input into a grammatical sentence in the same language."""

    def __init__(self, model, tokenizer):
        self._model = model
        self._tokenizer = tokenizer

    def rephrase(self, text: str) -> str:
        _, rephrased_text = generate_answer(self._model, self._tokenizer, REPHRASE_SYSTEM_PROMPT, text)
        return rephrased_text
