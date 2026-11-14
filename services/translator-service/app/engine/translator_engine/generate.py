import re
from collections.abc import Iterator

from mlx_lm import generate, stream_generate

MAX_NEW_TOKENS = 512

# Qwen3 is a reasoning model — by default it prefixes its reply with a <think>...</think> block
# before the actual answer. Split that out instead of leaking it into the translation.
THINK_BLOCK = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def generate_answer(model, tokenizer, system_prompt: str, user_text: str) -> tuple[str, str]:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
        chat_template_kwargs={"reasoning_effort": "low"}
    )
    response = generate(model, tokenizer, prompt=prompt, max_tokens=MAX_NEW_TOKENS)

    match = THINK_BLOCK.search(response)
    if match is None:
        return "", response.strip()
    thinking = match.group(1).strip()
    answer = response[match.end() :].strip()
    return thinking, answer


def stream_answer(model, tokenizer, system_prompt: str, user_text: str) -> Iterator[str]:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
    )

    buffer = ""
    answer_started = False
    for response in stream_generate(model, tokenizer, prompt=prompt, max_tokens=MAX_NEW_TOKENS):
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
        # matching generate_answer()'s fallback when THINK_BLOCK doesn't match.
        yield buffer.strip()
