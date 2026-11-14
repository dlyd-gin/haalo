from ....config import SUPPORTED_LANGUAGES

SYSTEM_PROMPT = (
    "You are a professional translator. Translate the user's message from {source} to {target}. "
    "Respond with only the translated text — no explanations, no quotes, no additional commentary."
)


def build_system_prompt(source_language: str, target_language: str) -> str:
    return SYSTEM_PROMPT.format(
        source=SUPPORTED_LANGUAGES[source_language],
        target=SUPPORTED_LANGUAGES[target_language],
    )
