import unicodedata

_KANA_SHARE = 0.1  # Japanese mixes kanji with kana; this share of kana among CJK letters marks it as Japanese
_MIN_LETTERS = 2  # fewer letters than this (e.g. a bare price) can't tell a language


def detect_language(text: str) -> str | None:
    """The SUPPORTED_LANGUAGES code ("en", "jp", "zh", "ko") whose script dominates text, by counting
    letters per Unicode block; digits and punctuation don't count. Han alone can't tell Chinese from
    Japanese, so any real share of kana makes it Japanese. None when there are too few letters."""
    latin = han = kana = hangul = 0
    for ch in text:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if name.startswith("CJK UNIFIED IDEOGRAPH") or name.startswith("CJK COMPATIBILITY IDEOGRAPH"):
            han += 1
        elif name.startswith(("HIRAGANA", "KATAKANA", "HALFWIDTH KATAKANA")):
            kana += 1
        elif name.startswith("HANGUL"):
            hangul += 1
        elif name.startswith("LATIN"):
            latin += 1
    cjk = han + kana + hangul
    if cjk + latin < _MIN_LETTERS:
        return None
    if cjk < latin:
        return "en"
    if hangul >= han + kana:
        return "ko"
    if kana >= _KANA_SHARE * (han + kana):
        return "jp"
    return "zh"
