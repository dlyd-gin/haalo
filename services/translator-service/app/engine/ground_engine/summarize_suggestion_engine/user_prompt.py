from ..giveme_suggestion_engine.addon import ADDON_LINE


def build_summarize_prompt(intent: str, highlights: list[str]) -> str:
    """Highlights come in document order, and giveme-suggestion always highlights an add-on's dish
    too, so a "+ ..." add-on is nested under the dish bullet right before it. That keeps the dish in
    the summary ("GREEN BOWL with poached egg") instead of the add-on standing alone."""
    lines: list[str] = []
    for highlight in highlights:
        text = highlight.strip()
        if ADDON_LINE.match(text) and lines:
            lines.append(f"  - add-on: {text.lstrip('+').strip()}")
        else:
            lines.append(f"- {text}")
    return f"INTENT:\n{intent}\n\nHIGHLIGHTS:\n" + "\n".join(lines)
