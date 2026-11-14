import logging
from typing import Any

from ....config import (
    GIVEME_INTENT_MAX_TOKENS,
    GIVEME_MAX_TOKENS,
    GIVEME_TEMPERATURE,
    GIVEME_TOP_K,
    GIVEME_TOP_P,
)
from ..parse import THINK_BLOCK
from ..spans import resolve_spans
from .addon import extend_addon_parents
from .intent_prompt import INTENT_SYSTEM_PROMPT, build_intent_prompt, copies_document
from .parse import parse_suggestions
from .script import detect_language
from .system_prompt import SUGGEST_SYSTEM_PROMPT_PLAIN, SUGGEST_SYSTEM_PROMPT_REASON
from .user_prompt import build_suggest_prompt

logger = logging.getLogger(__name__)


class GivemeSuggestionEngine:
    """Prompts the already-loaded chat-tuned LLM to pick the document items that fit an intent."""

    def __init__(self, model, tokenizer):
        self._model = model
        self._tokenizer = tokenizer

    def suggest(
        self, intent: str, context: list[str], include_reason: bool = False
    ) -> list[dict[str, Any]]:
        from mlx_lm import generate  # lazy: keeps the pure helpers importable without MLX
        from mlx_lm.sample_utils import make_sampler

        translated_intent = self._translate_intent(intent, context)
        messages = [
            {
                "role": "system",
                "content": SUGGEST_SYSTEM_PROMPT_REASON if include_reason else SUGGEST_SYSTEM_PROMPT_PLAIN,
            },
            {"role": "user", "content": build_suggest_prompt(intent, context, translated_intent)},
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=True
        )
        logger.debug("suggest: prompt:\n%s", prompt)
        sampler = make_sampler(temp=GIVEME_TEMPERATURE, top_p=GIVEME_TOP_P, top_k=GIVEME_TOP_K)
        response = generate(
            self._model, self._tokenizer, prompt=prompt, max_tokens=GIVEME_MAX_TOKENS, sampler=sampler
        )
        logger.debug("suggest: raw model output: %r", response)
        items = parse_suggestions(response, include_reason)
        resolved = resolve_spans(items, context)
        spans = extend_addon_parents(resolved, context)
        logger.debug(
            "suggest: parsed %d items, resolved %d spans, added %d add-on parent dishes",
            len(items), len(resolved), len(spans) - len(resolved),
        )
        return spans

    def _translate_intent(self, intent: str, context: list[str]) -> str | None:
        """The intent rewritten into the document's language and script, when the two differ (e.g. an
        English intent on a Traditional Chinese menu), so matching becomes a near-literal lookup instead
        of the model translating in its head into the wrong script. None when no rewrite is needed."""
        from mlx_lm import generate

        intent_language, context_language = detect_language(intent), detect_language("\n".join(context))
        if intent_language is None or context_language is None or intent_language == context_language:
            return None
        messages = [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": build_intent_prompt(intent, context)},
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        response = generate(self._model, self._tokenizer, prompt=prompt, max_tokens=GIVEME_INTENT_MAX_TOKENS)
        translated = THINK_BLOCK.sub("", response).strip().splitlines()
        translated_intent = translated[0].strip() if translated else ""
        logger.debug(
            "suggest: intent %s -> %s rewritten as %r", intent_language, context_language, translated_intent
        )
        if translated_intent and copies_document(translated_intent, context):
            logger.debug("suggest: rewrite copied a document item, using the intent as given")
            return None
        return translated_intent or None
