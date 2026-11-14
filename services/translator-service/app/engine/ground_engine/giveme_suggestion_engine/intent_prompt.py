import re

_SAMPLE_LINES = 30
FILLER_LINE = re.compile(r"^[\s\d.,:;/+$%()\-]*$")  # prices, phone numbers, bare numbering

INTENT_SYSTEM_PROMPT = """
You rewrite a short INTENT (what someone is looking for in a document) into the language and writing system of the SAMPLE lines from that document.
Use the exact character forms the sample uses: Traditional or Simplified Chinese as the sample writes it, Japanese kanji and kana as the sample writes them, Korean Hangul.
Translate what is being looked for, keeping it as general as the INTENT: the SAMPLE only shows which language and character forms to use. Never replace the INTENT with a specific item from the SAMPLE, and drop filler words such as "please" or "I want".
For example, "beef noodle please" with a SAMPLE that lists 牛肉家常麵 gives 牛肉麵, not 牛肉家常麵.
Output only the rewritten INTENT, with no quotes, notes or explanation.
"""


def build_intent_prompt(intent: str, context: list[str]) -> str:
    """The INTENT plus the first document lines that carry text (not prices or numbers), so the model
    copies the document's own script variant rather than its default one."""
    sample = [line.strip() for line in context if line.strip() and not FILLER_LINE.match(line.strip())]
    return f"INTENT:\n{intent}\n\nSAMPLE:\n" + "\n".join(sample[:_SAMPLE_LINES])


def copies_document(rewrite: str, context: list[str]) -> bool:
    """Whether the rewritten intent is text lifted from the document (e.g. the shop name 牛肉家常麵 for
    "beef noodle please") rather than a translation: shown as the intent, the model then looks for that
    one item and misses the rest."""
    return any(rewrite in line for line in context)
