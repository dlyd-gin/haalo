from app.engine.ground_engine.giveme_suggestion_engine.addon import extend_addon_parents
from app.engine.ground_engine.giveme_suggestion_engine.intent_prompt import (
    INTENT_SYSTEM_PROMPT,
    build_intent_prompt,
    copies_document,
)
from app.engine.ground_engine.giveme_suggestion_engine.parse import parse_suggestions
from app.engine.ground_engine.giveme_suggestion_engine.script import detect_language
from app.engine.ground_engine.giveme_suggestion_engine.user_prompt import build_suggest_prompt
from app.engine.ground_engine.ground_state_engine.user_prompt import build_prompt
from app.engine.ground_engine.parse import parse_groundings
from app.engine.ground_engine.spans import resolve_spans

CONTEXT = ["The  quick brown fox", "jumps over", "the lazy dog"]


def test_build_prompt_numbers_lines():
    prompt = build_prompt("a fox", CONTEXT)
    assert prompt.startswith("STATE:\na fox")
    assert "[0] The  quick brown fox\n[1] jumps over\n[2] the lazy dog" in prompt


def test_parse_groundings_variants():
    raw = '[{"line": 0, "quote": "brown fox"}]'
    assert parse_groundings(raw) == [{"line": 0, "quote": "brown fox"}]
    assert parse_groundings(f"```json\n{raw}\n```") == [{"line": 0, "quote": "brown fox"}]
    assert parse_groundings(f"<think>x [1]</think>\n{raw}") == [{"line": 0, "quote": "brown fox"}]
    assert parse_groundings("[]") == []
    assert parse_groundings("no json here") == []
    assert parse_groundings("[{broken") == []
    assert parse_groundings('{"line": 0}') == []
    assert parse_groundings('[{"line": "x", "quote": "x"}, {"line": 1}, 3]') == []


def test_parse_groundings_accepts_digit_string_line_only():
    # the model sometimes writes "line": "14"; true / 1.5 / "x" are still rejected
    raw = '[{"line": "14", "quote": "a"}, {"line": true, "quote": "b"}, {"line": 1.5, "quote": "c"}, {"line": "1a", "quote": "d"}]'
    assert parse_groundings(raw) == [{"line": 14, "quote": "a"}]


def test_resolve_spans_exact_and_offsets():
    spans = resolve_spans([{"line": 1, "quote": "over"}], CONTEXT)
    assert spans == [{"line": 1, "start": 6, "end": 10}]


def test_resolve_spans_case_and_whitespace_fallback():
    assert resolve_spans([{"line": 2, "quote": "LAZY DOG"}], CONTEXT) == [{"line": 2, "start": 4, "end": 12}]
    # model collapsed the double space in the line
    assert resolve_spans([{"line": 0, "quote": "The quick"}], CONTEXT) == [{"line": 0, "start": 0, "end": 10}]


def test_resolve_spans_drops_invalid_line_and_blank_quote_and_dedupes():
    items = [
        {"line": 9, "quote": "x"},
        {"line": -1, "quote": "x"},
        {"line": 1, "quote": "  "},
        {"line": 1, "quote": "over"},
        {"line": 1, "quote": "over"},
    ]
    assert resolve_spans(items, CONTEXT) == [{"line": 1, "start": 6, "end": 10}]


WRAPPED = [
    "Intro",
    "As you can appreciate, some owners do not want to spend money at all, or do not communicate their",
    "particular requirements (ie more parking, bbq area, etc). If you want to adjust the Plan within six",
    "months, there is no charge.",
]


def test_resolve_spans_quote_spanning_two_lines():
    quote = (
        "As you can appreciate, some owners do not want to spend money at all, "
        "or do not communicate their particular requirements (ie more parking, bbq area, etc)."
    )
    spans = resolve_spans([{"line": 1, "quote": quote}], WRAPPED)
    assert spans == [
        {"line": 1, "start": 0, "end": len(WRAPPED[1])},
        {"line": 2, "start": 0, "end": WRAPPED[2].index("etc).") + len("etc).")},
    ]


def test_resolve_spans_quote_starting_mid_line_over_three_lines():
    spans = resolve_spans([{"line": 1, "quote": "communicate their particular requirements (ie more parking, bbq area, etc). If you want to adjust the Plan within six months, there"}], WRAPPED)
    assert [s["line"] for s in spans] == [1, 2, 3]
    assert spans[0]["start"] == WRAPPED[1].index("communicate")
    assert spans[2] == {"line": 3, "start": 0, "end": len("months, there")}


def test_resolve_spans_whole_line_fallback_when_quote_not_found():
    spans = resolve_spans([{"line": 3, "quote": "nothing like this appears"}], WRAPPED)
    assert spans == [{"line": 3, "start": 0, "end": len(WRAPPED[3])}]


def test_resolve_spans_relocates_quote_given_the_wrong_line():
    # From the log: "牛肉乾麵" is on line 24, the model said line 26 ("10酢醬麵90").
    menu = ["x"] * 24 + ["8牛肉乾麵180", "9家常乾麵90", "10酢醬麵90", "11涼麵/麻醬麵90"]
    assert resolve_spans([{"line": 26, "quote": "牛肉乾麵"}], menu) == [{"line": 24, "start": 1, "end": 5}]


def test_resolve_spans_relocates_to_the_nearest_match():
    # Both copies lie outside the cross-line window after line 6; line 2 is nearer than line 13.
    lines = [str(i) for i in range(16)]
    lines[2] = lines[13] = "牛肉麵"
    assert resolve_spans([{"line": 6, "quote": "牛肉麵"}], lines) == [{"line": 2, "start": 0, "end": 3}]


def test_intent_prompt_translates_rather_than_picking_an_item():
    assert "Never replace the INTENT with a specific item" in INTENT_SYSTEM_PROMPT


def test_resolve_spans_quote_running_off_end_of_context_does_not_crash():
    spans = resolve_spans([{"line": 3, "quote": "there is no charge. And more that is not there"}], WRAPPED)
    assert spans == [{"line": 3, "start": 0, "end": len(WRAPPED[3])}]


def test_build_suggest_prompt_has_intent_and_numbered_lines():
    prompt = build_suggest_prompt("something light", ["Ramen", "Salad"])
    assert "STATE" not in prompt
    assert "INTENT:\nsomething light" in prompt
    assert "[0] Ramen\n[1] Salad" in prompt


CHINESE_MENU = [
    "老山東牛肉家常麵帳單", "TEL:23891216", "請寫上桌號:", "人數:", "內", "外", "品 名", "單 價",
    "11涼麵/麻醬麵", "90", "12豬肉韭菜水餃", "15個", "135", "10個", "90", "13牛肉湯餃(豬肉)", "15個", "160",
]


def test_build_suggest_prompt_adds_intent_in_context_language():
    prompt = build_suggest_prompt("Pork and chive dumplings", ["12豬肉韭菜水餃"], "豬肉韭菜水餃")
    assert (
        "INTENT:\nPork and chive dumplings\n(meaning, in the CONTEXT's language: 豬肉韭菜水餃. "
        "Match items by what they are, not by these characters.)\n\nCONTEXT:"
    ) in prompt
    assert build_suggest_prompt("x", ["a"], None) == build_suggest_prompt("x", ["a"])


def test_detect_language_en_jp_zh_ko():
    assert detect_language("Pork and chive dumplings") == "en"
    assert detect_language("\n".join(CHINESE_MENU)) == "zh"  # a stray "TEL:23891216" doesn't flip it
    assert detect_language("豚肉とニラの餃子") == "jp"  # kanji + kana
    assert detect_language("餃子が食べたい") == "jp"
    assert detect_language("돼지고기 부추 만두") == "ko"
    assert detect_language("190") is None
    assert detect_language("+10") is None


def test_build_intent_prompt_samples_text_lines_only():
    prompt = build_intent_prompt("Pork and chive dumplings", CHINESE_MENU)
    assert prompt.startswith("INTENT:\nPork and chive dumplings\n\nSAMPLE:\n")
    sample = prompt.split("SAMPLE:\n", 1)[1].splitlines()
    assert "12豬肉韭菜水餃" in sample and "15個" in sample
    assert "90" not in sample and "135" not in sample


def test_suggest_prompt_matches_across_languages_and_item_numbers():
    from app.engine.ground_engine.giveme_suggestion_engine.system_prompt import (
        SUGGEST_SYSTEM_PROMPT_PLAIN,
        SUGGEST_SYSTEM_PROMPT_REASON,
    )

    for prompt in (SUGGEST_SYSTEM_PROMPT_PLAIN, SUGGEST_SYSTEM_PROMPT_REASON):
        assert "English, Japanese, Chinese or Korean" in prompt
        assert "豬=猪" in prompt
        assert "document's own item number" in prompt
        assert "title, shop name or a section header" in prompt
        assert "what an item's own text rules out" in prompt
        assert "never a string to search for" in prompt
    assert '12. "reason"' in SUGGEST_SYSTEM_PROMPT_REASON


def test_parse_suggestions_reason_flag():
    raw = '<think>x</think>```json\n[{"line": 1, "quote": "Salad", "reason": " low calorie "}, {"line": 0, "quote": "Ramen"}]\n```'
    assert parse_suggestions(raw, True) == [
        {"line": 1, "quote": "Salad", "reason": "low calorie"},
        {"line": 0, "quote": "Ramen"},
    ]
    assert all("reason" not in item for item in parse_suggestions(raw, False))
    assert parse_suggestions("nope", True) == []


def test_resolve_spans_carries_reason():
    items = [{"line": 1, "quote": "Salad", "reason": "light"}]
    assert resolve_spans(items, ["Ramen", "Green Salad"]) == [
        {"line": 1, "start": 6, "end": 11, "reason": "light"}
    ]


MENU = [
    "GREEN BOWL steamed & raw shaved broccoli, avocado, brown",
    "rice, crispy shallot, chilli, lemon, parsley, sesame",
    "CRACK SAUCE chilli, crunchy shallot, sesame",
    "ZHOUG coriander, jalapeno,",
]


def test_suggest_prompt_asks_for_whole_item():
    from app.engine.ground_engine.giveme_suggestion_engine.system_prompt import (
        SUGGEST_SYSTEM_PROMPT_PLAIN,
        SUGGEST_SYSTEM_PROMPT_REASON,
    )

    for prompt in (SUGGEST_SYSTEM_PROMPT_PLAIN, SUGGEST_SYSTEM_PROMPT_REASON):
        assert "ENTIRE suggested item" in prompt
        assert "__REASON" not in prompt
        assert "ANY of them" in prompt  # multi-part intents ("X with Y") match each part on its own
        assert "add-on" in prompt and '"+ BACON"' in prompt
        assert "belongs to the dish listed directly above it" in prompt
        assert "not \"+ CHEESE\"" in prompt


def test_resolve_spans_whole_menu_items():
    items = [
        {"line": 2, "quote": "CRACK SAUCE chilli, crunchy shallot, sesame"},
        {"line": 3, "quote": "ZHOUG coriander, jalapeno,"},
        {"line": 0, "quote": "GREEN BOWL steamed & raw shaved broccoli, avocado, brown rice, crispy shallot, chilli, lemon, parsley, sesame"},
    ]
    assert resolve_spans(items, MENU) == [
        {"line": 0, "start": 0, "end": len(MENU[0])},
        {"line": 1, "start": 0, "end": len(MENU[1])},
        {"line": 2, "start": 0, "end": len(MENU[2])},
        {"line": 3, "start": 0, "end": len(MENU[3])},
    ]


def test_resolve_spans_multi_part_intent_dish_and_addon():
    context = [
        "LEBS-BENEDICT poached eggs with your choice of grilled sujuk, or streaky bacon, smoked butter hollandaise",
        "26",
        "+ BACON",
        "+10",
    ]
    items = [
        {"line": 0, "quote": context[0]},
        {"line": 2, "quote": "+ BACON"},
    ]
    assert resolve_spans(items, context) == [
        {"line": 0, "start": 0, "end": len(context[0])},
        {"line": 2, "start": 0, "end": 7},
    ]


def test_resolve_spans_addon_only_of_requested_dish():
    context = [
        "A BIT SWEET...",
        "FRENCH TOAST strawberries and cream, sablè",
        "24",
        "+ VANILLA ICE CREAM",
        "+5",
        "PISTACHIO HOTCAKE pistachio cream",
        "19",
        "+ ADD HOTCAKE",
        "+7",
    ]
    items = [{"line": 1, "quote": context[1]}, {"line": 3, "quote": "+ VANILLA ICE CREAM"}]
    assert resolve_spans(items, context) == [
        {"line": 1, "start": 0, "end": len(context[1])},
        {"line": 3, "start": 0, "end": 19},
    ]


PAGE_5 = [
    "LEBS-BENEDICT poached eggs with your choice of grilled sujuk, or streaky bacon, smoked butter hollandaise",
    "26",
    "MISC. TURKISH EGGS two poached eggs, sourdough, smoked labneh, crack sauce, aleppo pepper, chilli, sesame",
    "22",
    "+ MINI PITA",
    "+3",
    "+ BACON",
    "+10",
    "+CHORIZO",
    "+10",
    "MUSHROOM FOLD OVER PITA black garlic and truffle butter, flat mushroom, rocket,",
    "V",
    "23",
    "+ EXTRA MUSHROOM",
    "+4",
    "A BIT SWEET...",
    "+ ORPHAN",
    "+1",
]


def test_extend_addon_parents_highlights_dish_of_addon():
    spans = [
        {"line": 0, "start": 0, "end": len(PAGE_5[0])},
        {"line": 6, "start": 0, "end": 7},
    ]
    assert extend_addon_parents(spans, PAGE_5) == [
        {"line": 0, "start": 0, "end": len(PAGE_5[0])},
        {"line": 2, "start": 0, "end": len(PAGE_5[2])},
        {"line": 6, "start": 0, "end": 7},
    ]


def test_extend_addon_parents_addon_without_space_and_no_duplicate():
    spans = [
        {"line": 2, "start": 0, "end": len(PAGE_5[2])},
        {"line": 6, "start": 0, "end": 7},
        {"line": 8, "start": 0, "end": 8},
    ]
    assert extend_addon_parents(spans, PAGE_5) == spans


def test_extend_addon_parents_skips_dietary_tag():
    spans = [{"line": 13, "start": 0, "end": len(PAGE_5[13])}]
    assert extend_addon_parents(spans, PAGE_5)[0] == {"line": 10, "start": 0, "end": len(PAGE_5[10])}


def test_extend_addon_parents_no_parent_under_header_or_at_top():
    spans = [{"line": 16, "start": 0, "end": 8}]
    assert extend_addon_parents(spans, PAGE_5) == spans
    context = ["+ BACON", "+10"]
    spans = [{"line": 0, "start": 0, "end": 7}]
    assert extend_addon_parents(spans, context) == spans


def test_extend_addon_parents_ignores_non_addon_spans_and_copies_reason():
    assert extend_addon_parents([{"line": 3, "start": 0, "end": 2}], PAGE_5) == [{"line": 3, "start": 0, "end": 2}]
    spans = [{"line": 6, "start": 0, "end": 7, "reason": "bacon add-on"}]
    assert extend_addon_parents(spans, PAGE_5)[0] == {
        "line": 2, "start": 0, "end": len(PAGE_5[2]), "reason": "bacon add-on",
    }


def test_build_summarize_prompt_lists_highlights():
    from app.engine.ground_engine.summarize_suggestion_engine.user_prompt import build_summarize_prompt

    prompt = build_summarize_prompt("something light", ["Garden salad", "Miso soup"])
    assert prompt == "INTENT:\nsomething light\n\nHIGHLIGHTS:\n- Garden salad\n- Miso soup"


def test_build_summarize_prompt_groups_addons_under_their_dish():
    from app.engine.ground_engine.summarize_suggestion_engine.user_prompt import build_summarize_prompt

    prompt = build_summarize_prompt(
        "something with eggs",
        ["GREEN BOWL broccoli, avocado", "+ POACHED EGG", "+BACON", "LEBS-BENEDICT poached eggs"],
    )
    assert prompt.endswith(
        "HIGHLIGHTS:\n"
        "- GREEN BOWL broccoli, avocado\n"
        "  - add-on: POACHED EGG\n"
        "  - add-on: BACON\n"
        "- LEBS-BENEDICT poached eggs"
    )


def test_build_summarize_prompt_addon_without_dish_stays_top_level():
    from app.engine.ground_engine.summarize_suggestion_engine.user_prompt import build_summarize_prompt

    prompt = build_summarize_prompt("eggs", ["+ POACHED EGG", "TURKISH EGGS"])
    assert prompt.endswith("HIGHLIGHTS:\n- + POACHED EGG\n- TURKISH EGGS")


BEEF_MENU = ["老山東牛肉家常麵帳單", "TEL:23891216", "1牛肉家常麵", "190", "2全筋家常麵", "220", "3半筋半肉麵", "220"]


def test_copies_document_catches_a_rewrite_lifted_from_the_menu():
    assert copies_document("牛肉家常麵", BEEF_MENU)  # the shop name / item 1, not a translation
    assert not copies_document("牛肉麵", BEEF_MENU)
