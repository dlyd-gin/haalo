import logging

from ....config import GROUND_MAX_TOKENS
from ..parse import parse_groundings
from ..spans import resolve_spans
from .system_prompt import GROUND_SYSTEM_PROMPT
from .user_prompt import build_prompt

logger = logging.getLogger(__name__)


class GroundStateEngine:
    """Prompts the already-loaded chat-tuned LLM to locate a state inside document lines."""

    def __init__(self, model, tokenizer):
        self._model = model
        self._tokenizer = tokenizer

    def ground(self, state: str, context: list[str]) -> list[dict[str, int]]:
        from mlx_lm import generate  # lazy: keeps the pure helpers importable without MLX

        messages = [
            {"role": "system", "content": GROUND_SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(state, context)},
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        logger.debug("ground: prompt:\n%s", prompt)
        response = generate(self._model, self._tokenizer, prompt=prompt, max_tokens=GROUND_MAX_TOKENS)
        logger.debug("ground: raw model output: %r", response)
        items = parse_groundings(response)
        spans = resolve_spans(items, context)
        logger.debug("ground: parsed %d items, resolved %d spans", len(items), len(spans))
        return spans
