def build_suggest_prompt(intent: str, context: list[str], translated_intent: str | None = None) -> str:
    """translated_intent is the INTENT already rewritten into the CONTEXT's language, when they differ."""
    if translated_intent:
        intent = (
            f"{intent}\n(meaning, in the CONTEXT's language: {translated_intent}. "
            "Match items by what they are, not by these characters.)"
        )
    return f"INTENT:\n{intent}\n\nCONTEXT:\n" + "\n".join(
        f"[{i}] {line}" for i, line in enumerate(context)
    )
