def build_prompt(state: str, context: list[str]) -> str:
    numbered = "\n".join(f"[{i}] {line}" for i, line in enumerate(context))
    return f"STATE:\n{state}\n\nCONTEXT:\n{numbered}"
