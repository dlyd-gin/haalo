import re
from collections.abc import Iterator

from mlx_lm import generate, load, stream_generate

from .config import SUPPORTED_LANGUAGES

MAX_NEW_TOKENS = 512

REPHRASE_SYSTEM_PROMPT = """
# Role
You are an expert Query Pre-processor and Multilingual Grammar Correction AI. Your sole job is to rewrite broken, grammatically incorrect, or poorly structured user queries into proper, natural sentences.

# Core Directive
Analyze the user's input. Identify the underlying language and the user's intent. Rewrite the text into a clean, complete, and grammatically perfect sentence in that same language. 

# Strict Operational Rules
1. **Preserve Intent:** Never change the core meaning of the user's request. If the user is asking about the volume of a cup, do not rewrite it to ask about the price.
2. **Language Matching:** Keep the output in the same language as the input (e.g., rewrite broken Japanese into proper Japanese, broken English into proper English).
3. **No Fluff:** Output ONLY the corrected sentence. Do not include greetings, explanations, notes, or punctuation marks like quotes around the final output.
4. **Handle Ambiguity Safely:** If a query has two possible meanings due to broken grammar, choose the path that makes the most logical sense based on standard conversational context.

# Example
Incorrect: how long will it keep after opening the seal?
Correct: How long can it be stored after opening?

# Execution
Process the following user input now. Respond with nothing but the corrected sentence.
"""


SYSTEM_PROMPT = (
    "You are a professional translator. Translate the user's message from {source} to {target}. "
    "Respond with only the translated text — no explanations, no quotes, no additional commentary."
)

# Qwen3 is a reasoning model — by default it prefixes its reply with a <think>...</think> block
# before the actual answer. Split that out instead of leaking it into the translation.
THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL)


class TranslatorEngine:
    """Wraps mlx-lm model loading and prompts a chat-tuned LLM to translate."""

    def __init__(self, model_path: str):
        self._model, self._tokenizer = load(model_path)

    def _generate(self, system_prompt: str, user_text: str) -> tuple[str, str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        response = generate(self._model, self._tokenizer, prompt=prompt, max_tokens=MAX_NEW_TOKENS)

        match = THINK_BLOCK.search(response)
        if match is None:
            return "", response.strip()
        thinking = match.group(1).strip()
        answer = response[match.end() :].strip()
        return thinking, answer

    def translate(self, text: str, source_language: str, target_language: str) -> tuple[str, str, str]:
        # Step 1: rephrase the raw user input for grammar/clarity before translating it.
        _, rephrased_text = self._generate(REPHRASE_SYSTEM_PROMPT, text)

        # Step 2: run the existing translation prompt against the rephrased text.
        thinking, answer = self._generate(
            SYSTEM_PROMPT.format(
                source=SUPPORTED_LANGUAGES[source_language],
                target=SUPPORTED_LANGUAGES[target_language],
            ),
            rephrased_text,
        )
        return thinking, answer, rephrased_text

    def _generate_stream(self, system_prompt: str, user_text: str) -> Iterator[str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )

        buffer = ""
        answer_started = False
        for response in stream_generate(self._model, self._tokenizer, prompt=prompt, max_tokens=MAX_NEW_TOKENS):
            print(f"[translator-service] token: {response.text!r} (buffering={not answer_started})")
            if answer_started:
                if response.text:
                    yield response.text
                continue

            buffer += response.text
            close_idx = buffer.find("</think>")
            if close_idx == -1:
                continue
            answer_started = True
            remainder = buffer[close_idx + len("</think>") :].lstrip()
            if remainder:
                yield remainder

        if not answer_started and buffer:
            # No <think> block ever showed up — treat the whole response as the answer,
            # matching _generate()'s fallback when THINK_BLOCK doesn't match.
            yield buffer.strip()

    def translate_stream(
        self, text: str, source_language: str, target_language: str
    ) -> Iterator[dict[str, str]]:
        # Step 1: rephrase the raw user input for grammar/clarity before translating it (blocking —
        # this pass isn't shown to the user, only the translation pass below streams).
        _, rephrased_text = self._generate(REPHRASE_SYSTEM_PROMPT, text)

        # Step 2: stream the translation prompt against the rephrased text.
        answer_parts: list[str] = []
        for delta in self._generate_stream(
            SYSTEM_PROMPT.format(
                source=SUPPORTED_LANGUAGES[source_language],
                target=SUPPORTED_LANGUAGES[target_language],
            ),
            rephrased_text,
        ):
            answer_parts.append(delta)
            yield {"type": "delta", "text": delta}

        yield {"type": "done", "answer": "".join(answer_parts), "rephrased_text": rephrased_text}
