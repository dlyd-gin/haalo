import asyncio
import io
import os

import pytest
from PIL import Image

from fastapi.testclient import TestClient

from app.engine.docx_engine.image_docx import _fit_font, image_docx as _image_docx
from app.engine.pdf_engine.elements import page_markdown as _page_markdown
from app.engine.pdf_engine.image import (
    extract_page_images as _extract_page_images,
    image_type as _image_type,
    merge_bboxes as _merge_bboxes,
    pad_bbox as _pad_bbox,
)
from app.engine.pdf_engine.layout import (
    calibrate_x_tolerance_ratio as _calibrate_x_tolerance_ratio,
    join_line as _join_line,
    otsu_threshold as _otsu_threshold,
)
from app.engine.pdf_engine.page_number import select_printed_page as _select_printed_page
from app.engine.pdf_engine.table import (
    extract_page_tables as _extract_page_tables,
    split_leftovers as _split_leftovers,
    table_to_markdown as _table_to_markdown,
)
from app.engine.pdf_engine.text import (
    extract_page_text as _extract_page_text,
    extract_pages_batched as _extract_pages_batched,
)
from app.main import app

from app.config import ANNOTATE_DPI, GAP_SEPARATOR

PAGE_WIDTH = 600.0


def _minimal_pdf_bytes(page_texts: list[str]) -> bytes:
    """Build a minimal valid PDF with one page per entry in page_texts, each page's content
    stream showing exactly that text. pdfplumber can only read PDFs, not write them, so tests
    that need real PDF bytes construct one by hand instead of relying on a fixture file."""
    n = len(page_texts)
    page_ids = [4 + 2 * i for i in range(n)]
    content_ids = [5 + 2 * i for i in range(n)]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)

    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n} >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, content_id, text in zip(page_ids, content_ids, page_texts):
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 3 0 R >> >> "
            f"/MediaBox [0 0 200 200] /Contents {content_id} 0 R >>"
        )
        stream = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET"
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"

    body = b"%PDF-1.4\n"
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(body)
        body += f"{obj_id} 0 obj\n{objects[obj_id]}\nendobj\n".encode()

    max_id = max(objects)
    xref_offset = len(body)
    body += f"xref\n0 {max_id + 1}\n".encode()
    body += b"0000000000 65535 f \n"
    for obj_id in range(1, max_id + 1):
        body += f"{offsets[obj_id]:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return body


def _pdf_with_content_stream(content_stream: str) -> bytes:
    """Build a minimal single-page PDF from a raw content stream, for tests that need to control
    text positioning directly (e.g. simulating a TJ-array word gap instead of a literal space
    glyph) rather than just showing a plain string via _minimal_pdf_bytes."""
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: "<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 500 200] /Contents 5 0 R >>",
        4: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        5: f"<< /Length {len(content_stream)} >>\nstream\n{content_stream}\nendstream",
    }
    body = b"%PDF-1.4\n"
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(body)
        body += f"{obj_id} 0 obj\n{objects[obj_id]}\nendobj\n".encode()
    max_id = max(objects)
    xref_offset = len(body)
    body += f"xref\n0 {max_id + 1}\n".encode()
    body += b"0000000000 65535 f \n"
    for obj_id in range(1, max_id + 1):
        body += f"{offsets[obj_id]:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return body


def _tight_gap_sentence_pdf(sentence: str, font_size: int = 8, gap_adjustment: int = -300) -> bytes:
    """Build a PDF that renders `sentence` via a single TJ array with `gap_adjustment` between
    each word instead of a literal space glyph - simulating how many PDF generators (esp.
    justified body text) render inter-word spacing, which is what triggers the word-merging bug
    fixed by x_tolerance_ratio calibration (see _extract_page_text)."""
    words = sentence.split(" ")
    parts = []
    for i, word in enumerate(words):
        parts.append(f"({word})")
        if i != len(words) - 1:
            parts.append(str(gap_adjustment))
    content = f"BT /F1 {font_size} Tf 10 150 Td [{''.join(parts)}] TJ ET"
    return _pdf_with_content_stream(content)


def test_extract_page_text_returns_page_content():
    pdf_bytes = _minimal_pdf_bytes(["Hello World", "Second Page"])
    assert _extract_page_text(pdf_bytes, 1)["text"] == "Hello World"
    assert _extract_page_text(pdf_bytes, 2)["text"] == "Second Page"


def test_extract_page_text_out_of_range_raises():
    pdf_bytes = _minimal_pdf_bytes(["Only Page"])
    with pytest.raises(ValueError):
        _extract_page_text(pdf_bytes, 2)


def test_extract_page_text_invalid_pdf_raises():
    with pytest.raises(ValueError):
        _extract_page_text(b"not a pdf", 1)


def test_extract_page_text_auto_calibration_fixes_tj_gap_word_merging():
    # Reproduces the reported bug: a justified-text PDF renders word gaps as a small TJ-array
    # position adjustment (here -300 at 8pt = 2.4pt, under pdfplumber's fixed 3pt default
    # x_tolerance), which merges words with no space unless the gap is judged relative to font
    # size instead of a fixed point value.
    sentence = "The key objective of a 10 Year Plan is to determine the annual contribution"
    pdf_bytes = _tight_gap_sentence_pdf(sentence)
    assert _extract_page_text(pdf_bytes, 1)["text"] == sentence


def test_extract_page_text_explicit_ratio_overrides_calibration():
    sentence = "The key objective of a 10 Year Plan"
    pdf_bytes = _tight_gap_sentence_pdf(sentence)
    # An absurdly large explicit x_tolerance_ratio should still take effect over auto-calibration,
    # collapsing every word gap back into one merged run of text.
    result = _extract_page_text(pdf_bytes, 1, x_tolerance_ratio=5.0)
    assert result["x_tolerance_ratio"] == 5.0
    assert result["text"] == sentence.replace(" ", "")


def test_extract_pages_batched_preserves_input_order():
    pdf_bytes = _minimal_pdf_bytes(["One", "Two", "Three"])
    results = asyncio.run(_extract_pages_batched(pdf_bytes, [3, 1, 2], batch_size=4))
    assert [r["page"] for r in results] == [3, 1, 2]
    assert [r["text"] for r in results] == ["Three", "One", "Two"]


def test_extract_pages_batched_with_batch_size_one():
    pdf_bytes = _minimal_pdf_bytes(["Alpha", "Beta"])
    results = asyncio.run(_extract_pages_batched(pdf_bytes, [1, 2], batch_size=1))
    assert [r["text"] for r in results] == ["Alpha", "Beta"]


def _char(text: str, x0: float, x1: float, size: float, top: float = 0.0) -> dict:
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + size, "size": size}


def test_otsu_threshold_separates_bimodal_clusters():
    # Mirrors the scenarios validated during design: a tight low cluster (within-word kerning)
    # and a clearly separated higher cluster (between-word gaps) - the threshold should land
    # strictly between the two, regardless of the clusters' exact location/spread.
    low = [0.01, 0.015, 0.02, 0.018, 0.022, 0.012] * 10
    high = [0.27, 0.28, 0.29, 0.26, 0.3] * 10
    threshold = _otsu_threshold(low + high)
    assert max(low) < threshold < min(high)


def test_calibrate_x_tolerance_ratio_uses_own_document_clusters():
    size = 10.0
    line = [_char("a", 0.0, 9.0, size)]  # anchor char; gaps are measured from here on
    x = 9.0
    # 20 tiny "kerning" gaps (~0.02 x size) followed by a handful of larger "word" gaps (~0.3 x size)
    for _ in range(20):
        line.append(_char("a", x + 0.02 * size, x + 0.02 * size + 9.0, size))
        x = line[-1]["x1"]
    for _ in range(10):
        line.append(_char("a", x + 0.3 * size, x + 0.3 * size + 9.0, size))
        x = line[-1]["x1"]

    ratio = _calibrate_x_tolerance_ratio(line, fallback=0.2)
    assert 0.02 < ratio < 0.3


def test_calibrate_x_tolerance_ratio_falls_back_when_too_few_samples():
    chars = [_char("a", i * 10.0, i * 10.0 + 9.0, 10.0) for i in range(5)]
    assert _calibrate_x_tolerance_ratio(chars, fallback=0.2, min_samples=30) == 0.2


def _word(text: str, x0: float, x1: float, top: float = 0.0, bottom: float | None = None) -> dict:
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 10.0 if bottom is None else bottom}


def _line(*texts: str) -> list[dict]:
    words = []
    x0 = 10.0
    for text in texts:
        x1 = x0 + max(len(text), 1) * 8
        words.append(_word(text, x0, x1))
        x0 = x1 + 5
    return words


def test_bare_number_in_right_zone():
    words = [_word("12", 550, 570)]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == "12"


def test_bare_number_in_left_zone_is_discarded():
    words = [_word("12", 50, 70)]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == ""


def test_page_label_wins_even_in_left_zone():
    words = [_word("Page", 10, 40), _word("12", 45, 60)]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == "Page 12"


def test_page_label_with_roman_numeral():
    words = [_word("Page", 10, 40), _word("iv", 45, 60)]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=False) == "Page iv"


def test_page_of_total_fraction():
    words = [
        _word("Page", 10, 40),
        _word("3", 45, 55),
        _word("of", 60, 75),
        _word("45", 80, 100),
    ]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == "Page 3 of 45"


def test_annex_with_dash_connector():
    words = [
        _word("Annex", 10, 50),
        _word("1", 55, 65),
        _word("-", 70, 75),
        _word("Page", 80, 110),
        _word("3", 115, 125),
    ]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == "Annex 1 - Page 3"


def test_annex_with_of_connector():
    words = [
        _word("Annex", 10, 50),
        _word("1", 55, 65),
        _word("of", 70, 85),
        _word("Page", 90, 120),
        _word("1", 125, 135),
    ]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=False) == "Annex 1 of Page 1"


def test_no_candidates_returns_empty_string():
    words = [_word("Confidential", 200, 300)]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == ""


def test_number_embedded_in_prose_is_not_a_page_number():
    # e.g. a wrapped header title like "...over the 10 Year capital..." — "10" sits in the
    # center zone but is part of a sentence, not a standalone page number.
    words = [
        _word("over", 150, 180),
        _word("the", 185, 205),
        _word("10", 210, 230),
        _word("Year", 235, 260),
        _word("capital", 265, 310),
    ]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=False) == ""


def test_bare_number_with_decorative_dashes_still_matches():
    words = [_word("-", 530, 535), _word("12", 540, 560), _word("-", 565, 570)]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == "12"


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (("Schedule", "B", "-", "Page", "4"), "Schedule B - Page 4"),
        (("Exhibit", "A,", "Page", "2"), "Exhibit A, Page 2"),
        (("Table", "3", "-", "Page", "12"), "Table 3 - Page 12"),
        (("Sec.", "5", "Page", "9"), "Sec. 5 Page 9"),
        (("Vol.", "II", "-", "Page", "7"), "Vol. II - Page 7"),
        (("Attachment", "1", "of", "Page", "3"), "Attachment 1 of Page 3"),
    ],
)
def test_broad_section_label_vocabulary(tokens, expected):
    assert _select_printed_page(_line(*tokens), PAGE_WIDTH, prefer_bottom=True) == expected


def test_section_label_survives_short_punctuation_glyph():
    # A hyphen's bounding box is much shallower than surrounding letters (e.g. top=5,bottom=8 vs
    # top=0,bottom=10 for the letters), which used to split "Annex A - Page 2" into two separate
    # "lines" and lose the "Annex A" prefix.
    words = [
        _word("Annex", 10, 50, top=0),
        _word("A", 55, 65, top=0),
        _word("-", 70, 78, top=5, bottom=8),
        _word("Page", 85, 115, top=0),
        _word("2", 120, 130, top=0),
    ]
    assert _select_printed_page(words, PAGE_WIDTH, prefer_bottom=True) == "Annex A - Page 2"


def _ruled_table_content(prose: str = "") -> str:
    """Content stream: a line of text above a 2x3 ruled grid (label | value), optionally with a
    prose paragraph in a third column of the same box, like the 'Assumptions' sample."""
    ops = ["BT /F1 10 Tf 20 180 Td (Note: figures are rounded) Tj ET"]
    right = 300 if prose else 200
    for y in (150, 120, 90, 60):
        # inner rules stop at the value column so the prose cell is one merged cell, as in the sample
        edge = right if y in (150, 60) else 200
        ops.append(f"20 {y} m {edge} {y} l S")
    for x in (20, 140, 200) + ((300,) if prose else ()):
        ops.append(f"{x} 150 m {x} 60 l S")
    for row, (label, value) in enumerate([("Item", "Cost"), ("Buffer", "$1,850"), ("Rate", "2.00%")]):
        y = 132 - 30 * row
        ops.append(f"BT /F1 10 Tf 25 {y} Td ({label}) Tj ET BT /F1 10 Tf 145 {y} Td ({value}) Tj ET")
    if prose:
        words = prose.split()  # wrap 2 words per line so the paragraph stays inside its cell
        for i in range(0, len(words), 2):
            ops.append(f"BT /F1 5 Tf 205 {141 - 5 * (i // 2)} Td ({' '.join(words[i:i + 2])}) Tj ET")
    return "\n".join(ops)


def test_table_to_markdown_escapes_pipes_and_drops_empty_columns():
    md, paragraphs = _table_to_markdown([["a|b", "", "c"], ["1", "", "2\n3"]])
    assert md == "| a\\|b | c |\n| --- | --- |\n| 1 | 2 3 |"
    assert paragraphs == []


def test_table_to_markdown_pads_ragged_rows():
    md, _ = _table_to_markdown([["h1", "h2"], ["x"]])
    assert md.splitlines()[-1] == "| x |  |"


def test_table_to_markdown_moves_prose_cell_out_of_table():
    prose = " ".join(["word"] * 30)
    md, paragraphs = _table_to_markdown([["k", "v", prose], ["k2", "v2", None]])
    assert md == "| k | v |\n| --- | --- |\n| k2 | v2 |"
    assert paragraphs == [prose]


def test_table_to_markdown_all_empty_returns_empty():
    assert _table_to_markdown([[None, ""], ["", None]]) == ("", [])


# CJK glyphs are a full em wide; measuring them as Latin picked fonts that wrapped onto a second
# line the exact-height frame then clipped (e.g. "1牛肉家常麵" at 19pt in a 71.5pt frame).
_CJK_ITEM_EM = 0.56 + 5 * 1.0  # "1" + five ideographs


def test_fit_font_measures_cjk_as_full_width():
    size, lines = _fit_font("1牛肉家常麵", 64.0, 22.5)
    assert lines == 1
    assert _CJK_ITEM_EM * size <= 64.0


def test_image_docx_cjk_line_fits_its_frame():
    import re
    import zipfile

    content = _image_docx([{"text": "1牛肉家常麵", "bbox": [80, 194, 161, 224]}], 600, 1000)
    xml = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml").decode()
    frame_w_pt = int(re.search(r'w:framePr w:w="(\d+)"', xml).group(1)) / 20
    size_pt = int(re.search(r'w:sz w:val="(\d+)"', xml).group(1)) / 2
    assert _CJK_ITEM_EM * size_pt <= frame_w_pt


def test_extract_page_tables_renders_text_then_table():
    result = _extract_page_tables(_pdf_with_content_stream(_ruled_table_content()), 1)
    assert result is not None
    assert len(result["tables"]) == 1
    md = result["markdown"]
    assert md.index("Note: figures are rounded") < md.index("| Item | Cost |")
    assert "| Buffer | $1,850 |" in md
    assert len(result["tables"][0]["bbox"]) == 4


def test_extract_page_tables_prose_cell_follows_table_as_text():
    prose = " ".join(["Recommendation"] * 30)
    result = _extract_page_tables(_pdf_with_content_stream(_ruled_table_content(prose)), 1)
    assert result is not None
    md = result["markdown"]
    assert "Recommendation" in md
    assert md.index("| Buffer | $1,850 |") < md.index("Recommendation")
    assert "Recommendation" not in result["tables"][0]["markdown"]


def test_extract_page_tables_without_table_returns_plain_text():
    result = _extract_page_tables(_minimal_pdf_bytes(["hello world"]), 1)
    assert result == {"markdown": "hello world", "tables": [], "recovered_text": False}


def test_extract_page_tables_scanned_page_returns_none():
    assert _extract_page_tables(_pdf_with_content_stream("0 0 m 10 10 l S"), 1) is None


def test_extract_page_tables_out_of_range_raises():
    with pytest.raises(ValueError, match="out of range"):
        _extract_page_tables(_minimal_pdf_bytes(["x"]), 5)


client = TestClient(app)


def _post_tables(pdf: bytes, **data):
    return client.post("/extract-tables", files={"file": ("d.pdf", pdf, "application/pdf")}, data=data)


def test_extract_tables_endpoint_returns_markdown():
    resp = _post_tables(_pdf_with_content_stream(_ruled_table_content()))
    assert resp.status_code == 200
    body = resp.json()
    assert body["page_count"] == 1
    assert "| Item | Cost |" in body["pages"][0]["markdown"]


def test_extract_tables_endpoint_204_when_only_scanned_pages():
    resp = _post_tables(_pdf_with_content_stream("0 0 m 10 10 l S"))
    assert resp.status_code == 204
    assert resp.content == b""


def test_extract_tables_endpoint_omits_scanned_pages_when_others_have_text():
    resp = _post_tables(_minimal_pdf_bytes(["one", "two"]), pages=[2])
    assert [p["page"] for p in resp.json()["pages"]] == [2]


@pytest.mark.parametrize(
    "pdf, data",
    [
        (b"", {}),
        (b"not a pdf", {}),
        (_minimal_pdf_bytes(["x"]), {"pages": [3]}),
        (_minimal_pdf_bytes(["x"]), {"batch_size": 0}),
    ],
)
def test_extract_tables_endpoint_400s(pdf, data):
    resp = _post_tables(pdf, **data)
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_extract_page_tables_keeps_text_beside_and_below_table():
    content = _ruled_table_content() + (
        "\nBT /F1 8 Tf 230 110 Td (SideNote beside grid) Tj ET"
        "\nBT /F1 8 Tf 20 30 Td (Footer line below) Tj ET"
    )
    result = _extract_page_tables(_pdf_with_content_stream(content), 1)
    assert result is not None
    md = result["markdown"]
    for text in ("Note: figures are rounded", "SideNote beside grid", "Footer line below", "| Item | Cost |"):
        assert text in md
    assert md.index("SideNote") < md.index("| Item | Cost |") < md.index("Footer line below")


def _w(text: str, top: float = 0.0, x0: float = 0.0) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + 10, "top": top, "bottom": top + 10}


def test_split_leftovers_ignores_words_in_cells_and_orders_lines():
    cells = [(0, 50, 100, 100)]
    words = [_w("Payment", top=60), _w("Page", top=10, x0=80), _w("PAYMENT", top=10), _w("below", top=120)]
    assert _split_leftovers(words, cells, (0, 50, 100, 70)) == ([f"PAYMENT{GAP_SEPARATOR}Page"], ["below"])


def test_split_leftovers_line_level_with_first_row_counts_as_header():
    cells = [(0, 50, 60, 100)]  # boxed "PAYMENT PLAN" cell; the title sits beside it, level with row 1
    words = [_w("Title", top=60, x0=70), _w("later", top=90, x0=70)]
    assert _split_leftovers(words, cells, (0, 50, 60, 80)) == (["Title"], ["later"])


def test_split_leftovers_repeated_words_are_not_masked():
    # "Plan" also lives in a cell; the header's "Plan" must still be reported.
    cells = [(0, 50, 100, 100)]
    words = [_w("Plan", top=60), _w("Plan", top=10)]
    assert _split_leftovers(words, cells, (0, 50, 100, 100)) == (["Plan"], [])


def test_extract_page_tables_header_inside_bbox_but_outside_cells(monkeypatch):
    class FakeTable:
        bbox = (10.0, 20.0, 490.0, 150.0)
        cells = [(10.0, 60.0, 490.0, 150.0)]

        class _Row:
            bbox = (10.0, 60.0, 490.0, 150.0)

        rows = [_Row()]

        def extract(self, **_):
            return [["Payment", "Plan"], ["of", "x"]]

    monkeypatch.setattr("app.engine.pdf_engine.table.find_tables", lambda page: [FakeTable()])
    content = (
        "BT /F1 10 Tf 20 165 Td (PAYMENT PLAN) Tj ET\n"
        "BT /F1 8 Tf 110 165 Td (Recommended Payment Plan and verification of our Recommendations) Tj ET\n"
        "BT /F1 10 Tf 455 165 Td (Page 5) Tj ET\n"
        "BT /F1 10 Tf 20 100 Td (Payment) Tj ET BT /F1 10 Tf 150 100 Td (Plan) Tj ET"
    )
    result = _extract_page_tables(_pdf_with_content_stream(content), 1)
    md = result["markdown"]
    header = f"PAYMENT PLAN Recommended Payment Plan and verification of our Recommendations{GAP_SEPARATOR}Page 5"
    assert header in md
    assert md.index(header) < md.index("| Payment | Plan |")
    assert result["recovered_text"] is True


def test_extract_page_tables_recovers_stray_text_inside_table_box():
    content = _ruled_table_content() + "\nBT /F1 8 Tf 160 100 Td (Stray) Tj ET"  # inside box, in the value column
    result = _extract_page_tables(_pdf_with_content_stream(content), 1)
    assert result is not None
    assert result["markdown"].count("Stray") == 1
    for text in ("Note: figures are rounded", "| Item | Cost |"):
        assert text in result["markdown"]


def test_extract_page_tables_clean_page_has_no_recovered_text():
    result = _extract_page_tables(_pdf_with_content_stream(_ruled_table_content()), 1)
    assert result["recovered_text"] is False


def test_extract_page_tables_title_level_with_boxed_first_cell_comes_first(monkeypatch):
    """The boxed 'PAYMENT PLAN' cell is row 1; the title line sits level with it but outside every
    cell (inside the table bbox), and must still be written before the table."""

    class FakeTable:
        bbox = (10.0, 20.0, 490.0, 150.0)
        cells = [(10.0, 20.0, 100.0, 60.0), (10.0, 60.0, 490.0, 150.0)]

        class _Row:
            bbox = (10.0, 20.0, 490.0, 60.0)

        rows = [_Row()]

        def extract(self, **_):
            return [["PAYMENT PLAN", ""], ["Year", "Amount"]]

    monkeypatch.setattr("app.engine.pdf_engine.table.find_tables", lambda page: [FakeTable()])
    content = (
        "BT /F1 10 Tf 20 165 Td (PAYMENT PLAN) Tj ET\n"
        "BT /F1 8 Tf 110 165 Td (Recommended Payment Plan and verification of our Recommendations) Tj ET\n"
        "BT /F1 10 Tf 455 165 Td (Page 5) Tj ET\n"
        "BT /F1 10 Tf 20 100 Td (Year) Tj ET BT /F1 10 Tf 150 100 Td (Amount) Tj ET"
    )
    md = _extract_page_tables(_pdf_with_content_stream(content), 1)["markdown"]
    title = f"Recommended Payment Plan and verification of our Recommendations{GAP_SEPARATOR}Page 5"
    assert md.index(title) < md.index("| PAYMENT PLAN |")


def test_join_line_uses_gap_separator_only_for_wide_gaps():
    from app.config import GAP_SEPARATOR

    # word height 10 -> threshold 25pt: "a b" gap is 4, "b c" gap is 100
    line = [
        {"text": "a", "x0": 0, "x1": 10, "top": 0, "bottom": 10},
        {"text": "b", "x0": 14, "x1": 24, "top": 0, "bottom": 10},
        {"text": "c", "x0": 124, "x1": 134, "top": 0, "bottom": 10},
    ]
    assert _join_line(line) == f"a b{GAP_SEPARATOR}c"


def test_extract_page_text_separates_far_apart_segments_and_lines():
    from app.config import GAP_SEPARATOR

    content = (
        "BT /F1 10 Tf 10 150 Td (PAYMENT PLAN) Tj ET "
        "BT /F1 10 Tf 200 150 Td (Recommended Plan) Tj ET "
        "BT /F1 10 Tf 440 150 Td (Page 5) Tj ET "
        "BT /F1 10 Tf 10 100 Td (Second line) Tj ET"
    )
    text = _extract_page_text(_pdf_with_content_stream(content), 1)["text"]
    assert text == f"PAYMENT PLAN{GAP_SEPARATOR}Recommended Plan{GAP_SEPARATOR}Page 5\nSecond line"


def test_extract_page_tables_non_table_text_keeps_segment_gaps():
    from app.config import GAP_SEPARATOR

    content = "BT /F1 10 Tf 10 150 Td (Left) Tj ET BT /F1 10 Tf 400 150 Td (Right) Tj ET"
    result = _extract_page_tables(_pdf_with_content_stream(content), 1)
    assert result["markdown"] == f"Left{GAP_SEPARATOR}Right"


def test_extract_page_tables_leftover_header_line_keeps_segment_gap():
    # header line crosses the top of the ruled grid's bbox but sits outside its cells
    content = _ruled_table_content() + (
        "\nBT /F1 10 Tf 210 152 Td (Recommendations) Tj ET BT /F1 10 Tf 400 152 Td (Page 5) Tj ET"
    )
    md = _extract_page_tables(_pdf_with_content_stream(content), 1)["markdown"]
    assert f"Recommendations{GAP_SEPARATOR}Page 5" in md


def test_extract_page_text_returns_line_and_page_bboxes():
    content = (
        "BT /F1 10 Tf 10 150 Td (Left) Tj ET BT /F1 10 Tf 400 150 Td (Right) Tj ET "
        "BT /F1 10 Tf 10 100 Td (Second line) Tj ET"
    )
    result = _extract_page_text(_pdf_with_content_stream(content), 1)
    first, second = result["lines"]
    assert "\n".join(l["text"] for l in result["lines"]) == result["text"]
    assert first["bbox"][0] < 15 and first["bbox"][2] > 400 and first["bbox"][1] < first["bbox"][3]
    assert second["bbox"][1] > first["bbox"][3]
    assert result["bbox"] == [first["bbox"][0], first["bbox"][1], first["bbox"][2], second["bbox"][3]]


def test_extract_page_text_blank_page_has_no_bbox():
    result = _extract_page_text(_pdf_with_content_stream(""), 1)
    assert result["lines"] == [] and result["bbox"] is None and result["text"] == ""


def _pdf_with_image(
    filter_entry: str = "",
    pages: int = 1,
    image_on_pages: tuple[int, ...] = (1,),
    draw: str = "q 50 0 0 40 20 100 cm /Im1 Do Q",
) -> bytes:
    """Build a PDF whose pages in image_on_pages each draw a 1x1 DeviceGray image XObject scaled
    to 50x40pt at (20, 100) on a 200x200pt page (so bbox = [20, 60, 70, 100] top-left origin)."""
    page_ids = [4 + 2 * i for i in range(pages)]
    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] /Count {pages} >>",
        3: f"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 {filter_entry} /Length 1 >>\nstream\n\x80\nendstream",
    }
    for i, page_id in enumerate(page_ids):
        stream = draw if i + 1 in image_on_pages else ""
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im1 3 0 R >> >> "
            f"/MediaBox [0 0 200 200] /Contents {page_id + 1} 0 R >>"
        )
        objects[page_id + 1] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    body = b"%PDF-1.4\n"
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(body)
        body += f"{obj_id} 0 obj\n{objects[obj_id]}\nendobj\n".encode("latin-1")
    max_id = max(objects)
    xref_offset = len(body)
    body += f"xref\n0 {max_id + 1}\n".encode()
    body += b"0000000000 65535 f \n"
    for obj_id in range(1, max_id + 1):
        body += f"{offsets[obj_id]:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return body


def test_extract_page_images_returns_bbox_and_metadata():
    (image,) = _extract_page_images(_pdf_with_image("/Filter /DCTDecode"), 1)["images"]
    assert image["bbox"] == pytest.approx([20, 60, 70, 100])
    assert (image["width_px"], image["height_px"]) == (1, 1)
    assert image["dpi"] == pytest.approx([1.44, 1.8])  # 1px over 50pt and 40pt
    assert image["page_coverage"] == pytest.approx(0.05)  # 50*40 / (200*200)
    assert image["type"] == "jpeg"
    assert image["colorspace"] == "DeviceGray"


def test_extract_page_images_none_on_page():
    assert _extract_page_images(_pdf_with_image(pages=2, image_on_pages=(1,)), 2) == {"images": []}


def test_extract_page_images_out_of_range_and_invalid_raise():
    with pytest.raises(ValueError, match="out of range"):
        _extract_page_images(_pdf_with_image(), 3)
    with pytest.raises(ValueError, match="invalid PDF"):
        _extract_page_images(b"not a pdf", 1)


@pytest.mark.parametrize(
    "filter_entry, expected",
    [
        ("", "raw"),
        ("/Filter /FlateDecode", "raw"),
        ("/Filter /DCTDecode", "jpeg"),
        ("/Filter /JPXDecode", "jpeg2000"),
        ("/Filter /JBIG2Decode", "jbig2"),
        ("/Filter /CCITTFaxDecode", "ccitt"),
        ("/Filter [/FlateDecode /DCTDecode]", "jpeg"),
        ("/Filter [/ASCII85Decode /FlateDecode]", "raw"),
    ],
)
def test_extract_page_images_type_from_filter(filter_entry, expected):
    assert _extract_page_images(_pdf_with_image(filter_entry), 1)["images"][0]["type"] == expected


def test_image_type_without_stream_is_raw():
    assert _image_type(None) == "raw"


def _post_images(pdf: bytes, **data):
    return client.post("/extract-images", files={"file": ("d.pdf", pdf, "application/pdf")}, data=data)


def test_extract_images_endpoint_returns_every_page():
    resp = _post_images(_pdf_with_image(pages=2, image_on_pages=(2,)))
    assert resp.status_code == 200
    body = resp.json()
    assert body["page_count"] == 2
    assert [p["page"] for p in body["pages"]] == [1, 2]
    assert body["pages"][0]["images"] == []
    assert body["pages"][1]["images"][0]["bbox"] == pytest.approx([20, 60, 70, 100])


def test_extract_images_endpoint_filters_pages():
    resp = _post_images(_pdf_with_image(pages=2, image_on_pages=(1, 2)), pages=[2])
    assert [p["page"] for p in resp.json()["pages"]] == [2]


@pytest.mark.parametrize(
    "pdf, data",
    [
        (b"", {}),
        (b"not a pdf", {}),
        (_minimal_pdf_bytes(["x"]), {"pages": [3]}),
        (_minimal_pdf_bytes(["x"]), {"batch_size": 0}),
    ],
)
def test_extract_images_endpoint_400s(pdf, data):
    resp = _post_images(pdf, **data)
    assert resp.status_code == 400
    assert "error" in resp.json()


def _post_annotate(pdf: bytes, **data):
    return client.post("/annotate-images", files={"file": ("d.pdf", pdf, "application/pdf")}, data=data)


def _opened(resp) -> Image.Image:
    return Image.open(io.BytesIO(resp.content)).convert("RGB")


def _is_red(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel  # loose thresholds: JPEG compression softens a thin red line
    return r > g + 40 and r > b + 40


def test_annotate_images_returns_jpeg_with_boxes_drawn():
    resp = _post_annotate(_pdf_with_image())
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content[:2] == b"\xff\xd8"
    assert resp.headers["x-image-count"] == "1"
    img = _opened(resp)
    scale = ANNOTATE_DPI / 72
    assert img.size == (round(200 * scale), round(200 * scale))
    # bbox is [20, 60, 70, 100] in points: some pixel around its top edge's midpoint must be red
    x, y = round(45 * scale), round(60 * scale)
    assert any(_is_red(img.getpixel((x, y + dy))) for dy in range(-3, 4))


def test_annotate_images_page_without_images_is_plain_render():
    resp = _post_annotate(_pdf_with_image(pages=2, image_on_pages=(1,)), pages=[2])
    assert resp.status_code == 200
    assert resp.headers["x-image-count"] == "0"
    assert "page-2-annotated" in resp.headers["content-disposition"]
    img = _opened(resp)
    assert not any(_is_red(px) for px in img.get_flattened_data())


def test_annotate_images_defaults_to_first_page():
    resp = _post_annotate(_pdf_with_image(pages=2, image_on_pages=(1,)))
    assert resp.headers["x-image-count"] == "1"
    assert "page-1-annotated" in resp.headers["content-disposition"]


@pytest.mark.parametrize(
    "pdf, data",
    [
        (b"", {}),
        (b"not a pdf", {}),
        (_minimal_pdf_bytes(["x"]), {"pages": [3]}),
        (_minimal_pdf_bytes(["x"]), {"batch_size": 0}),
        (_minimal_pdf_bytes(["x", "y"]), {"pages": [1, 2]}),
        (_minimal_pdf_bytes(["x"]), {"margin": -1}),
    ],
)
def test_annotate_images_endpoint_400s(pdf, data):
    resp = _post_annotate(pdf, **data)
    assert resp.status_code == 400
    assert "error" in resp.json()


def _pdf_with_image_strips(strips: int) -> bytes:
    """One 50x40pt picture at (20, 100) drawn as `strips` abutting horizontal slices, the way some
    exporters emit a single image - pdfplumber reports each slice as its own image."""
    height = 40 / strips
    draw = " ".join(f"q 50 0 0 {height} 20 {100 + k * height} cm /Im1 Do Q" for k in range(strips))
    return _pdf_with_image(draw=draw)


def test_merge_bboxes_unions_overlapping_and_abutting():
    assert _merge_bboxes([[0, 0, 10, 10], [5, 5, 20, 20]]) == [[0, 0, 20, 20]]
    assert _merge_bboxes([[0, 0, 10, 10], [10.5, 0, 20, 10]]) == [[0, 0, 20, 10]]


def test_merge_bboxes_keeps_distant_boxes_apart():
    assert _merge_bboxes([[50, 50, 60, 60], [0, 0, 10, 10]]) == [[0, 0, 10, 10], [50, 50, 60, 60]]


def test_merge_bboxes_is_transitive_and_handles_empty():
    # A touches B, B touches C, A and C do not touch directly
    assert _merge_bboxes([[0, 0, 10, 10], [20, 0, 30, 10], [10, 0, 20, 10]]) == [[0, 0, 30, 10]]
    assert _merge_bboxes([]) == []


def test_merge_bboxes_collapses_chain_of_strips():
    strips = [[0, float(i), 50, float(i + 1)] for i in range(20)]
    assert _merge_bboxes(strips) == [[0, 0, 50, 20]]


def test_annotate_images_boxes_a_stripped_image_once_without_filling_it():
    pdf = _pdf_with_image_strips(20)
    raw = client.post("/extract-images", files={"file": ("d.pdf", pdf, "application/pdf")}).json()
    assert len(raw["pages"][0]["images"]) == 20  # extract-images still reports every fragment

    resp = _post_annotate(pdf)
    assert resp.headers["x-image-count"] == "1"
    img = _opened(resp)
    scale = ANNOTATE_DPI / 72
    center = (round(45 * scale), round(80 * scale))  # inside bbox [20, 60, 70, 100]
    assert not _is_red(img.getpixel(center))


def test_pad_bbox_expands_and_clamps_to_page():
    assert _pad_bbox([20, 60, 70, 100], 10, (0, 0, 200, 200)) == [10, 50, 80, 110]
    assert _pad_bbox([2, 3, 198, 199], 10, (0, 0, 200, 200)) == [0, 0, 200, 200]
    assert _pad_bbox([20, 60, 70, 100], 0, (0, 0, 200, 200)) == [20, 60, 70, 100]
    # Page bbox offset from the origin (CropBox shifted against the MediaBox): clamp to it, not (0, 0, w, h).
    assert _pad_bbox([0, 0, 419.25, 595.5], 0, (0, -8.58, 419.25, 586.92)) == [0, 0, 419.25, 586.92]


def _red_rows(img: Image.Image, x: int) -> list[int]:
    return [y for y in range(img.height) if _is_red(img.getpixel((x, y)))]


def test_annotate_images_margin_moves_outline_outward():
    scale = ANNOTATE_DPI / 72
    x = round(45 * scale)  # middle of the bbox's top edge
    plain = _red_rows(_opened(_post_annotate(_pdf_with_image())), x)
    padded = _red_rows(_opened(_post_annotate(_pdf_with_image(), margin=10)), x)
    # bbox top is 60pt; with margin 10 the top edge moves up to 50pt (and bottom down to 110pt)
    assert min(plain) == pytest.approx(60 * scale, abs=3)
    assert min(padded) == pytest.approx(50 * scale, abs=3)
    assert max(padded) == pytest.approx(110 * scale, abs=3)


def _pdf_with_text_and_image(content_stream: str) -> bytes:
    """Single 200x200 page with Helvetica /F1 and a 1x1 gray image XObject /Im1."""
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: "<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> /MediaBox [0 0 200 200] /Contents 5 0 R >>",
        4: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        5: f"<< /Length {len(content_stream)} >>\nstream\n{content_stream}\nendstream",
        6: "<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\nstream\n\x80\nendstream",
    }
    body = b"%PDF-1.4\n"
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(body)
        body += f"{obj_id} 0 obj\n{objects[obj_id]}\nendobj\n".encode("latin-1")
    xref_offset = len(body)
    body += b"xref\n0 7\n0000000000 65535 f \n"
    for obj_id in range(1, 7):
        body += f"{offsets[obj_id]:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return body


def _post_markdown(pdf: bytes, **data):
    return client.post("/extract-markdown", files={"file": ("d.pdf", pdf, "application/pdf")}, data=data)


def test_extract_markdown_stitches_text_table_and_image_in_source_order():
    # Top to bottom: heading, image, a note, then the ruled table (shifted down 60pt).
    stream = (
        "BT /F1 10 Tf 20 190 Td (Heading line) Tj ET\n"
        "q 50 0 0 40 20 140 cm /Im1 Do Q\n"
        "q 1 0 0 1 0 -60 cm\n" + _ruled_table_content() + "\nQ"
    )
    resp = _post_markdown(_pdf_with_text_and_image(stream))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert 'filename="page-1.md"' in resp.headers["content-disposition"]
    md = resp.text
    assert md.index("Heading line") < md.index("![<bbox[")
    assert md.index("![<bbox[") < md.index("Note: figures are rounded") < md.index("| Item | Cost |")
    assert md.count("Heading line") == 1


def test_page_markdown_table_and_text_without_duplication():
    md = _page_markdown(_pdf_with_content_stream(_ruled_table_content()), 1, None, 72)
    assert md.index("Note: figures are rounded") < md.index("| Item | Cost |")
    assert md.count("Buffer") == 1


def test_page_markdown_image_only_page_embeds_png():
    md = _page_markdown(_pdf_with_image(), 1, None, 72)
    assert md.startswith("![<bbox[20.00, 60.00, 70.00, 100.00]>image 1](data:image/png;base64,")


def test_page_markdown_blank_page_is_none():
    assert _page_markdown(_pdf_with_image(image_on_pages=()), 1, None, 72) is None


def test_extract_markdown_blank_page_is_204():
    assert _post_markdown(_pdf_with_image(image_on_pages=())).status_code == 204


@pytest.mark.parametrize(
    "pdf, data",
    [
        (b"", {}),
        (b"not a pdf", {}),
        (_pdf_with_image(), {"page": 3}),
        (_pdf_with_image(), {"x_tolerance_ratio": 0}),
        (_pdf_with_image(), {"image_dpi": 0}),
    ],
)
def test_extract_markdown_rejects_bad_requests(pdf, data):
    resp = _post_markdown(pdf, **data)
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_extract_markdown_removes_temp_file(monkeypatch):
    removed = []
    real_unlink = os.unlink
    monkeypatch.setattr("app.feature.extract_markdown.os.unlink", lambda p: (removed.append(p), real_unlink(p)))
    assert _post_markdown(_pdf_with_image()).status_code == 200
    assert len(removed) == 1 and not os.path.exists(removed[0])


def _aligned_prose_content() -> str:
    """Unruled text laid out in aligned columns: no ruling lines, but pdfplumber's text-alignment
    strategy reads it as a table."""
    rows = [("Item", "Cost", "Note"), ("Buffer", "1850", "fixed"), ("Rate", "200", "yearly"), ("Fee", "75", "once")]
    ops = []
    for r, row in enumerate(rows):
        for x, cell in zip((20, 100, 170), row):
            ops.append(f"BT /F1 10 Tf {x} {180 - 15 * r} Td ({cell}) Tj ET")
    return "\n".join(ops)


def test_page_markdown_does_not_invent_table_when_analyze_finds_none(monkeypatch):
    pdf = _pdf_with_content_stream(_aligned_prose_content())
    # Premise: the text-alignment fallback (what /extract-tables uses) would call this a table.
    assert "| --- |" in _extract_page_tables(pdf, 1)["markdown"]

    def boom(page):
        raise AssertionError("text-alignment fallback must not run for /extract-markdown")

    monkeypatch.setattr("app.engine.pdf_engine.table.find_tables", boom)
    md = _page_markdown(pdf, 1, None, 72)
    assert "| --- |" not in md
    assert "Buffer" in md and "Fee" in md


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def _post_words(pdf: bytes, **data):
    return client.post("/extract-words", files={"file": ("d.pdf", pdf, "application/pdf")}, data=data)


def _text_image_table_pdf() -> bytes:
    stream = (
        "BT /F1 10 Tf 20 190 Td (Heading line) Tj ET\n"
        "q 50 0 0 40 20 140 cm /Im1 Do Q\n"
        "q 1 0 0 1 0 -60 cm\n" + _ruled_table_content() + "\nQ"
    )
    return _pdf_with_text_and_image(stream)


def _docx_of(resp):
    import docx

    assert resp.status_code == 200
    return docx.Document(io.BytesIO(resp.content))


def _frames(document, part="body"):
    """(text, x, y, w, h) in points of every paragraph frame of the body, header or footer."""
    root = document.element.body if part == "body" else getattr(document.sections[0], part)._element
    out = []
    for p in root.iter(_W + "p"):
        fp = p.find(f"{_W}pPr/{_W}framePr")
        if fp is not None:
            g = lambda k: int(fp.get(_W + k)) / 20
            out.append(("".join(t.text for t in p.iter(_W + "t")), g("x"), g("y"), g("w"), g("h")))
    return out


def test_extract_words_returns_docx_file_with_page_size():
    resp = _post_words(_text_image_table_pdf())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert 'filename="page-1.docx"' in resp.headers["content-disposition"]
    section = _docx_of(resp).sections[0]
    assert (section.page_width.pt, section.page_height.pt) == (200, 200)
    assert (section.left_margin.pt, section.right_margin.pt) == (0, 0)  # top/bottom reserve the header/footer


def test_extract_words_text_frame_sits_at_its_bbox():
    document = _docx_of(_post_words(_text_image_table_pdf()))
    heading = next(f for f in _frames(document, "header") if f[0] == "Heading line")
    _, x, y, w, h = heading
    # the page is 200pt high; "Heading line" is drawn at x=20 with its baseline at y=190 from the bottom
    # (inside the top 10% band, so it lives in the Word header, still pinned to the same page position)
    assert x == pytest.approx(20, abs=0.1)
    assert 0 <= y < 20
    assert h > 0 and w > 30


def test_extract_words_image_anchored_at_its_bbox():
    document = _docx_of(_post_words(_text_image_table_pdf()))
    anchor = next(document.element.body.iter(_WP + "anchor"))
    pos = lambda axis: int(anchor.find(f"{_WP}{axis}/{_WP}posOffset").text) / 12700
    assert (pos("positionH"), pos("positionV")) == (20.0, 20.0)  # drawn at y=140..180 of a 200pt page
    extent = anchor.find(_WP + "extent")
    assert (int(extent.get("cx")) / 12700, int(extent.get("cy")) / 12700) == (50.0, 40.0)
    assert anchor.get("behindDoc") == "1"


def test_extract_words_table_is_a_floating_word_table_without_duplicate_text():
    document = _docx_of(_post_words(_text_image_table_pdf()))
    assert len(document.tables) == 1
    table = document.tables[0]
    assert table._tbl.find(f"{_W}tblPr/{_W}tblpPr") is not None
    cells = [c.text for row in table.rows for c in row.cells]
    assert "Item" in cells and "Cost" in cells
    assert not any("Cost" in f[0] for f in _frames(document))


def test_extract_words_wide_gap_becomes_separate_frames():
    stream = "BT /F1 10 Tf 10 150 Td (left) Tj 150 0 Td (right) Tj ET"
    frames = _frames(_docx_of(_post_words(_pdf_with_content_stream(stream))))
    assert [f[0] for f in frames] == ["left", "right"]
    assert frames[1][1] - frames[0][1] == pytest.approx(150, abs=0.1)


def test_extract_words_reading_order_is_top_to_bottom():
    stream = "BT /F1 10 Tf 20 150 Td (alpha) Tj 0 -30 Td (beta) Tj ET"
    frames = _frames(_docx_of(_post_words(_pdf_with_content_stream(stream))))
    assert [f[0] for f in frames] == ["alpha", "beta"]
    assert frames[0][2] < frames[1][2]


def test_extract_words_blank_page_is_204():
    assert _post_words(_pdf_with_image(image_on_pages=())).status_code == 204


@pytest.mark.parametrize(
    "pdf, data",
    [
        (b"", {}),
        (b"not a pdf", {}),
        (_minimal_pdf_bytes(["a"]), {"page": "3"}),
        (_minimal_pdf_bytes(["a"]), {"x_tolerance_ratio": "0"}),
        (_minimal_pdf_bytes(["a"]), {"image_dpi": "0"}),
    ],
)
def test_extract_words_bad_requests_are_400(pdf, data):
    assert _post_words(pdf, **data).status_code == 400


def test_extract_words_header_and_footer_text_go_to_header_and_footer_parts():
    stream = "BT /F1 10 Tf 20 190 Td (Top note) Tj 0 -90 Td (Middle) Tj 0 -90 Td (Page 7) Tj ET"
    document = _docx_of(_post_words(_pdf_with_content_stream(stream)))
    assert [f[0] for f in _frames(document, "header")] == ["Top note"]
    assert [f[0] for f in _frames(document, "footer")] == ["Page 7"]
    assert [f[0] for f in _frames(document)] == ["Middle"]
    (_, x, y, _, _) = _frames(document, "header")[0]
    assert x == pytest.approx(20, abs=0.1) and y < 20


def test_extract_words_without_band_text_has_empty_header_and_footer():
    document = _docx_of(_post_words(_pdf_with_content_stream("BT /F1 10 Tf 20 100 Td (Middle) Tj ET")))
    section = document.sections[0]
    assert section.header.is_linked_to_previous and section.footer.is_linked_to_previous


def test_extract_words_header_and_footer_reserve_page_margins():
    stream = "BT /F1 10 Tf 20 190 Td (Top note) Tj 0 -90 Td (Middle) Tj 0 -90 Td (Page 7) Tj ET"
    document = _docx_of(_post_words(_pdf_with_content_stream(stream)))
    section = document.sections[0]
    (_, _, hy, _, hh), (_, _, fy, _, _) = _frames(document, "header")[0], _frames(document, "footer")[0]
    assert section.top_margin.pt >= hy + hh
    assert section.bottom_margin.pt >= section.page_height.pt - fy
    assert section.top_margin.pt + section.bottom_margin.pt <= section.page_height.pt * 0.9 + 0.1
    assert section.header_distance.pt == pytest.approx(hy, abs=0.1)
    # the frames themselves are still pinned to the same page position
    assert hy < 20 and fy > 180


def test_extract_words_without_band_text_keeps_zero_margins():
    document = _docx_of(_post_words(_pdf_with_content_stream("BT /F1 10 Tf 20 100 Td (Middle) Tj ET")))
    section = document.sections[0]
    assert (section.top_margin.pt, section.bottom_margin.pt) == (0, 0)


def _table_stream(dy: float = 0) -> str:
    grid = "\n".join(_ruled_table_content().splitlines()[1:])  # drop the "Note" line above the grid
    return f"q 1 0 0 1 0 {dy} cm\n{grid}\nQ"


def _table_geometry(document):
    """(top, bottom, [row rule, row height in pt]) of the first table, from tblpY and trHeight."""
    tbl = document.tables[0]._tbl
    top = int(tbl.find(f"{_W}tblPr/{_W}tblpPr").get(_W + "tblpY")) / 20
    rows = [tr.find(f"{_W}trPr/{_W}trHeight") for tr in tbl.findall(_W + "tr")]
    heights = [int(r.get(_W + "val")) / 20 for r in rows]
    return top, top + sum(heights), [(r.get(_W + "hRule"), h) for r, h in zip(rows, heights)]


def test_extract_words_table_reaching_into_header_is_squeezed_below_it_keeping_its_bottom():
    # grid is 50..140pt from the top; shifting it up 45pt puts its top (5pt) inside the header band
    stream = "BT /F1 10 Tf 20 190 Td (Top note) Tj 0 -185 Td (Foot) Tj ET\n" + _table_stream(45)
    document = _docx_of(_post_words(_pdf_with_content_stream(stream)))
    section = document.sections[0]
    top, bottom, rows = _table_geometry(document)
    assert top >= section.top_margin.pt
    assert bottom == pytest.approx(95, abs=0.2)  # the bottom edge did not move (5 + 90)
    assert bottom <= section.page_height.pt - section.bottom_margin.pt + 0.1
    assert all(rule == "exact" for rule, _ in rows)


def test_extract_words_table_is_squeezed_to_end_above_the_footer(monkeypatch):
    monkeypatch.setattr("app.engine.pdf_engine.layout.MARGIN_RATIO", 0.4)  # header band 0-80pt, footer band 120-200pt
    stream = "BT /F1 10 Tf 20 190 Td (Top note) Tj 0 -130 Td 250 0 Td (Foot) Tj ET\n" + _table_stream()
    document = _docx_of(_post_words(_pdf_with_content_stream(stream)))
    section = document.sections[0]
    top, bottom, _ = _table_geometry(document)
    assert top >= section.top_margin.pt
    assert bottom <= section.page_height.pt - section.bottom_margin.pt + 0.1
    assert bottom - top < 90


def test_extract_words_table_inside_body_area_is_untouched():
    stream = "BT /F1 10 Tf 20 190 Td (Top note) Tj 0 -185 Td (Foot) Tj ET\n" + _table_stream()
    top, bottom, rows = _table_geometry(_docx_of(_post_words(_pdf_with_content_stream(stream))))
    assert top == pytest.approx(50, abs=0.2) and bottom == pytest.approx(140, abs=0.2)


def test_extract_words_all_pages_is_one_section_per_page():
    resp = _post_words(_minimal_pdf_bytes(["First page", "Second page", "Third page"]), all_pages="true")
    assert 'filename="d.docx"' in resp.headers["content-disposition"]
    document = _docx_of(resp)
    assert len(document.sections) == 3
    assert [(s.page_width.pt, s.page_height.pt) for s in document.sections] == [(200, 200)] * 3
    texts = [f[0] for f in _frames(document)]
    assert texts == ["First page", "Second page", "Third page"]
    # later sections have their own (empty) header/footer instead of inheriting the previous page's
    assert all(not s.header.is_linked_to_previous for s in document.sections[1:])


def test_extract_words_all_pages_skips_blank_pages():
    pdf = _minimal_pdf_bytes(["First page", "", "Third page"])
    document = _docx_of(_post_words(pdf, all_pages="true"))
    assert len(document.sections) == 2
    assert [f[0] for f in _frames(document)] == ["First page", "Third page"]


# --- /ground-state -----------------------------------------------------------------------------

def _docx_bytes(paragraphs: list[list[str]], table_cell: str | None = None) -> bytes:
    """Build a docx where each entry of `paragraphs` is one paragraph made of those runs."""
    from docx import Document

    doc = Document()
    for runs in paragraphs:
        p = doc.add_paragraph()
        for text in runs:
            p.add_run(text)
    if table_cell is not None:
        doc.add_table(rows=1, cols=1).cell(0, 0).text = table_cell
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _highlighted_text(docx_bytes: bytes) -> list[str]:
    from docx import Document

    doc = Document(io.BytesIO(docx_bytes))
    return [r.text for p in doc.paragraphs for r in p.runs if r.font.highlight_color is not None]


def test_docx_lines_skips_blank_and_includes_tables():
    from app.engine.docx_engine.highlight import docx_lines as _docx_lines

    data = _docx_bytes([["Hello ", "world"], [""], ["Second"]], table_cell="In table")
    assert _docx_lines(data) == ["Hello world", "Second", "In table"]


def test_highlight_docx_splits_run_and_spans_runs():
    from app.engine.docx_engine.highlight import highlight_docx as _highlight_docx

    data = _docx_bytes([["The quick brown fox"], ["Alpha ", "beta ", "gamma"]])
    out = _highlight_docx(
        data, [{"line": 0, "start": 4, "end": 9}, {"line": 1, "start": 3, "end": 9}]
    )
    from docx import Document

    doc = Document(io.BytesIO(out))
    assert [p.text for p in doc.paragraphs[:2]] == ["The quick brown fox", "Alpha beta gamma"]
    assert _highlighted_text(out) == ["quick", "ha ", "bet"]


def test_highlight_docx_highlights_table_cell():
    from app.engine.docx_engine.highlight import highlight_docx as _highlight_docx
    from docx import Document

    out = _highlight_docx(_docx_bytes([["x"]], table_cell="cell text"), [{"line": 1, "start": 0, "end": 4}])
    cell_runs = Document(io.BytesIO(out)).tables[0].cell(0, 0).paragraphs[0].runs
    assert [(r.text, r.font.highlight_color is not None) for r in cell_runs] == [("cell", True), (" text", False)]


def test_highlight_docx_ignores_invalid_groundings():
    from app.engine.docx_engine.highlight import highlight_docx as _highlight_docx

    data = _docx_bytes([["short"]])
    bad = [{"line": 5, "start": 0, "end": 2}, {"line": 0, "start": 3, "end": 99}, {"line": 0, "start": 2, "end": 2}]
    assert _highlight_docx(data, bad) is None


def _post_ground(data: bytes, monkeypatch, groundings=None, state="fox"):
    async def fake(state_, lines):
        return groundings or []

    monkeypatch.setattr("app.client.translator.request_groundings", fake)
    return client.post(
        "/ground-state", files={"file": ("doc.docx", data)}, data={"state": state}
    )


def test_ground_state_returns_highlighted_docx(monkeypatch):
    data = _docx_bytes([["The quick brown fox"]])
    res = _post_ground(data, monkeypatch, [{"line": 0, "start": 16, "end": 19}])
    assert res.status_code == 200
    assert "grounded-doc.docx" in res.headers["content-disposition"]
    assert _highlighted_text(res.content) == ["fox"]


def test_ground_state_404_when_nothing_grounded(monkeypatch):
    res = _post_ground(_docx_bytes([["text"]]), monkeypatch, [])
    assert res.status_code == 404
    res = _post_ground(_docx_bytes([["text"]]), monkeypatch, [{"line": 9, "start": 0, "end": 1}])
    assert res.status_code == 404


def test_ground_state_400_cases(monkeypatch):
    assert _post_ground(b"not a docx", monkeypatch).status_code == 400
    assert _post_ground(b"", monkeypatch).status_code == 400
    assert _post_ground(_docx_bytes([[""]]), monkeypatch).status_code == 400
    assert _post_ground(_docx_bytes([["text"]]), monkeypatch, state="  ").status_code == 400


def test_ground_state_502_when_translator_down(monkeypatch):
    monkeypatch.setattr("app.client.translator.TRANSLATOR_URL", "http://127.0.0.1:1")
    res = client.post(
        "/ground-state", files={"file": ("doc.docx", _docx_bytes([["text"]]))}, data={"state": "x"}
    )
    assert res.status_code == 502


# --- /giveme-suggestion ------------------------------------------------------------------------


from fastapi import HTTPException as _HTTPException


def _post_suggest(data: bytes, monkeypatch, suggestions=None, instruction="the fox", summary="Try the fox."):
    seen = {}

    async def fake(instruction_, lines):
        seen["instruction"], seen["lines"] = instruction_, lines
        return suggestions or []

    async def fake_summary(instruction_, highlights):
        seen["summary_args"] = (instruction_, highlights)
        if isinstance(summary, Exception):
            raise summary
        return summary

    monkeypatch.setattr("app.client.translator.request_suggestions", fake)
    monkeypatch.setattr("app.client.translator.request_summary", fake_summary)
    res = client.post(
        "/giveme-suggestion", files={"file": ("doc.docx", data)}, data={"instruction": instruction}
    )
    res.seen = seen
    return res


def _multipart_parts(res) -> list[tuple[dict[str, str], bytes]]:
    """(headers, body) of each part of a multipart/mixed response."""
    content_type = res.headers["content-type"]
    assert content_type.startswith("multipart/mixed; boundary=")
    delimiter = b"--" + content_type.split("boundary=", 1)[1].encode()
    chunks = res.content.split(delimiter)
    assert chunks[0] == b"" and chunks[-1] == b"--\r\n"
    parts = []
    for chunk in chunks[1:-1]:
        head, body = chunk[2:].split(b"\r\n\r\n", 1)  # drop the CRLF after the delimiter
        assert body.endswith(b"\r\n")
        headers = dict(line.split(": ", 1) for line in head.decode().split("\r\n"))
        parts.append((headers, body[:-2]))
    return parts


def test_giveme_suggestion_streams_docx_then_summary(monkeypatch):
    import json

    data = _docx_bytes([["The quick brown fox"], ["jumps over the dog"]])
    suggestions = [{"line": 0, "start": 16, "end": 19, "reason": "x"}, {"line": 1, "start": 15, "end": 18}]
    res = _post_suggest(data, monkeypatch, suggestions, " the fox ")
    assert res.status_code == 200
    (file_headers, file_body), (json_headers, json_body) = _multipart_parts(res)
    assert file_headers["Content-Type"].startswith("application/vnd.openxmlformats")
    assert "suggested-doc.docx" in file_headers["Content-Disposition"]
    assert _highlighted_text(file_body) == ["fox", "dog"]
    assert json_headers["Content-Type"] == "application/json"
    assert json.loads(json_body) == {"summary": "Try the fox.", "highlights": ["fox", "dog"]}
    assert res.seen["instruction"] == "the fox"
    assert res.seen["summary_args"] == ("the fox", ["fox", "dog"])


def test_giveme_suggestion_summary_failure_is_reported_in_its_part(monkeypatch):
    import json

    data = _docx_bytes([["The quick brown fox"]])
    res = _post_suggest(
        data, monkeypatch, [{"line": 0, "start": 16, "end": 19}],
        summary=_HTTPException(502, "translator service unavailable"),
    )
    assert res.status_code == 200
    (_, file_body), (_, json_body) = _multipart_parts(res)
    assert _highlighted_text(file_body) == ["fox"]
    assert json.loads(json_body) == {"error": "translator service unavailable", "highlights": ["fox"]}


def test_highlight_snippets_merges_and_orders_spans():
    from app.engine.docx_engine.highlight import highlight_snippets

    lines = ["The quick brown fox", "jumps over"]
    suggestions = [
        {"line": 1, "start": 0, "end": 5},
        {"line": 0, "start": 10, "end": 15},
        {"line": 0, "start": 12, "end": 19},
        {"line": 7, "start": 0, "end": 1},  # out of range: dropped
    ]
    assert highlight_snippets(lines, suggestions) == ["brown fox", "jumps"]


def test_giveme_suggestion_404_when_no_suggestion(monkeypatch):
    res = _post_suggest(_docx_bytes([["text"]]), monkeypatch, [])
    assert res.status_code == 404
    assert res.json() == {"error": "no suggestion found in document"}
    res = _post_suggest(_docx_bytes([["text"]]), monkeypatch, [{"line": 9, "start": 0, "end": 1}])
    assert res.status_code == 404


def test_giveme_suggestion_400_cases(monkeypatch):
    assert _post_suggest(b"not a docx", monkeypatch).status_code == 400
    assert _post_suggest(b"", monkeypatch).status_code == 400
    assert _post_suggest(_docx_bytes([[""]]), monkeypatch).status_code == 400
    assert _post_suggest(_docx_bytes([["text"]]), monkeypatch, instruction="  ").status_code == 400


def test_giveme_suggestion_502_when_translator_down(monkeypatch):
    monkeypatch.setattr("app.client.translator.TRANSLATOR_URL", "http://127.0.0.1:1")
    res = client.post(
        "/giveme-suggestion",
        files={"file": ("doc.docx", _docx_bytes([["text"]]))},
        data={"instruction": "x"},
    )
    assert res.status_code == 502



# --- /giveme-suggestion-pdf --------------------------------------------------------------------


def _pdf_page(content_stream: str, media_box: str = "0 0 500 200", page_extra: str = "") -> bytes:
    """Single-page PDF like _pdf_with_content_stream, with a configurable MediaBox (e.g. one not
    starting at the origin) and extra page-dictionary entries (e.g. /Rotate 90)."""
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [{media_box}] {page_extra} /Contents 5 0 R >>",
        4: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        5: f"<< /Length {len(content_stream)} >>\nstream\n{content_stream}\nendstream",
    }
    body = b"%PDF-1.4\n"
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(body)
        body += f"{obj_id} 0 obj\n{objects[obj_id]}\nendobj\n".encode()
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for obj_id in range(1, len(objects) + 1):
        body += f"{offsets[obj_id]:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode()
    return body


def _highlight_rects(pdf_bytes: bytes) -> list[list[float]]:
    from pypdf import PdfReader

    page = PdfReader(io.BytesIO(pdf_bytes)).pages[0]
    annots = [a.get_object() for a in page.get("/Annots") or []]
    return [[float(v) for v in a["/Rect"]] for a in annots if a["/Subtype"] == "/Highlight"]


def test_join_line_spans_offsets_slice_back_to_words():
    from app.engine.pdf_engine.layout import join_line_spans

    line = [
        {"text": "Left", "x0": 0, "x1": 20, "top": 0, "bottom": 10},
        {"text": "side", "x0": 22, "x1": 40, "top": 0, "bottom": 10},
        {"text": "Right", "x0": 200, "x1": 230, "top": 0, "bottom": 10},  # wide gap: GAP_SEPARATOR
    ]
    text, spans = join_line_spans(line)
    assert text == _join_line(line) == f"Left side{GAP_SEPARATOR}Right"
    assert [text[a:b] for a, b in spans] == ["Left", "side", "Right"]


def test_pdf_lines_reads_text_and_rejects_unusable_pdfs():
    from app.engine.pdf_engine.highlight import pdf_lines

    lines = pdf_lines(_pdf_page("BT /F1 12 Tf 10 100 Td (The quick brown fox) Tj ET"))
    assert [(l["page"], l["text"]) for l in lines] == [(0, "The quick brown fox")]
    with pytest.raises(ValueError, match="unsupported PDF"):
        pdf_lines(_pdf_page(""))  # no text layer
    with pytest.raises(ValueError, match="unsupported PDF"):
        pdf_lines(_pdf_page("BT /F1 12 Tf 10 100 Td (Sideways) Tj ET", page_extra="/Rotate 90"))
    with pytest.raises(ValueError, match="invalid PDF"):
        pdf_lines(b"not a pdf")


@pytest.mark.parametrize("media_box, baseline", [("0 0 500 200", 100), ("0 50 500 250", 150)])
def test_highlight_pdf_places_annotations_in_user_space(media_box, baseline):
    from app.engine.pdf_engine.highlight import highlight_pdf, pdf_lines

    # Td is relative to user space, so the baseline is at `baseline` whatever the MediaBox origin.
    data = _pdf_page(f"BT /F1 12 Tf 10 {baseline} Td (The quick brown fox) Tj ET", media_box)
    lines = pdf_lines(data)
    out = highlight_pdf(data, lines, [{"line": 0, "start": 4, "end": 9}, {"line": 0, "start": 16, "end": 19}])
    (quick, fox) = _highlight_rects(out)
    word = {w["text"]: w for _, _, w in lines[0]["words"]}
    for rect, name in ((quick, "quick"), (fox, "fox")):
        assert rect[0] == pytest.approx(word[name]["x0"]) and rect[2] == pytest.approx(word[name]["x1"])
        assert rect[1] < baseline < rect[3]


def test_highlight_pdf_partial_word_covers_only_its_chars():
    from app.engine.pdf_engine.highlight import highlight_pdf, pdf_lines

    data = _pdf_page("BT /F1 12 Tf 10 100 Td (The quick brown fox) Tj ET")
    lines = pdf_lines(data)
    (whole,) = _highlight_rects(highlight_pdf(data, lines, [{"line": 0, "start": 4, "end": 9}]))  # "quick"
    (part,) = _highlight_rects(highlight_pdf(data, lines, [{"line": 0, "start": 5, "end": 8}]))  # "uic"
    assert whole[0] < part[0] < part[2] < whole[2]


def test_highlight_pdf_none_without_valid_grounding():
    from app.engine.pdf_engine.highlight import highlight_pdf, pdf_lines

    data = _pdf_page("BT /F1 12 Tf 10 100 Td (The quick brown fox) Tj ET")
    lines = pdf_lines(data)
    assert highlight_pdf(data, lines, []) is None
    assert highlight_pdf(data, lines, [{"line": 3, "start": 0, "end": 1}]) is None
    assert highlight_pdf(data, lines, [{"line": 0, "start": 3, "end": 4}]) is None  # just the space


def _post_suggest_pdf(data: bytes, monkeypatch, suggestions=None, summary="Try the fox."):
    async def fake(instruction_, lines):
        return suggestions or []

    async def fake_summary(instruction_, highlights):
        return summary

    monkeypatch.setattr("app.client.translator.request_suggestions", fake)
    monkeypatch.setattr("app.client.translator.request_summary", fake_summary)
    return client.post(
        "/giveme-suggestion-pdf", files={"file": ("menu.pdf", data)}, data={"instruction": "the fox"}
    )


def test_giveme_suggestion_pdf_streams_highlighted_pdf_then_summary(monkeypatch):
    import json

    data = _pdf_page("BT /F1 12 Tf 10 100 Td (The quick brown fox) Tj ET")
    res = _post_suggest_pdf(data, monkeypatch, [{"line": 0, "start": 16, "end": 19}])
    assert res.status_code == 200
    (file_headers, file_body), (_, json_body) = _multipart_parts(res)
    assert file_headers["Content-Type"] == "application/pdf"
    assert "suggested-menu.pdf" in file_headers["Content-Disposition"]
    assert len(_highlight_rects(file_body)) == 1
    assert json.loads(json_body) == {"summary": "Try the fox.", "highlights": ["fox"]}


def test_giveme_suggestion_pdf_error_cases(monkeypatch):
    text_pdf = _pdf_page("BT /F1 12 Tf 10 100 Td (The quick brown fox) Tj ET")
    assert _post_suggest_pdf(_pdf_page(""), monkeypatch).status_code == 422  # no text layer: fall back
    assert _post_suggest_pdf(b"not a pdf", monkeypatch).status_code == 400
    assert _post_suggest_pdf(b"", monkeypatch).status_code == 400
    assert _post_suggest_pdf(text_pdf, monkeypatch, []).status_code == 404


# --- /image-to-words -------------------------------------------------------------------------

import app.client.ocr as _ocr
from fastapi import HTTPException as _HTTPException


def _png(width=800, height=600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def _post_image(data: bytes, name="menu.png"):
    return client.post("/image-to-words", files={"file": (name, data, "image/png")})


def _fake_ocr(monkeypatch, lines):
    async def fake(data, content_type):
        return lines

    monkeypatch.setattr(_ocr, "request_ocr_lines", fake)


def test_image_to_words_pins_lines_at_scaled_bboxes(monkeypatch):
    _fake_ocr(
        monkeypatch,
        [
            {"text": "second", "bbox": [58, 124, 524, 149]},
            {"text": "first", "bbox": [58, 83, 186, 107]},
        ],
    )
    resp = _post_image(_png())
    assert 'filename="menu.docx"' in resp.headers["content-disposition"]
    doc = _docx_of(resp)
    section = doc.sections[0]
    assert (section.page_width.pt, section.page_height.pt) == (600, 450)
    frames = _frames(doc)
    assert [f[0] for f in frames] == ["first", "second"]
    text, x, y, w, h = frames[0]
    assert (x, y, h) == (43.5, 62.25, 18.0)


def test_image_to_words_collapsed_boxes_are_stacked_below_and_page_grows(monkeypatch):
    _fake_ocr(
        monkeypatch,
        [
            {"text": "placed", "bbox": [58, 570, 524, 594]},
            {"text": "lost a", "bbox": [58, 600, 186, 600]},
            {"text": "lost b", "bbox": [58, 600, 70, 600]},
        ],
    )
    doc = _docx_of(_post_image(_png()))
    frames = {f[0]: f for f in _frames(doc)}
    assert set(frames) == {"placed", "lost a", "lost b"}
    assert frames["lost a"][2] >= frames["placed"][2] + frames["placed"][4]
    assert frames["lost b"][2] > frames["lost a"][2] and frames["lost b"][4] > 0
    assert doc.sections[0].page_height.pt > 450


def test_image_to_words_no_valid_boxes_stack_from_top(monkeypatch):
    _fake_ocr(monkeypatch, [{"text": "a", "bbox": [5, 9, 5, 9]}, {"text": "b", "bbox": [5, 9, 5, 9]}])
    frames = _frames(_docx_of(_post_image(_png())))
    assert [f[0] for f in frames] == ["a", "b"] and frames[0][2] == 0 and frames[1][2] > 0


@pytest.mark.parametrize("data", [b"", b"not an image"])
def test_image_to_words_bad_image_is_400(data):
    resp = _post_image(data)
    assert resp.status_code == 400 and "error" in resp.json()


def test_image_to_words_no_text_is_422(monkeypatch):
    _fake_ocr(monkeypatch, [{"text": "  ", "bbox": [0, 0, 10, 10]}])
    resp = _post_image(_png())
    assert resp.status_code == 422
    assert resp.json() == {"error": "no text detected in image"}


@pytest.mark.parametrize("status", [400, 502])
def test_image_to_words_ocr_failure_is_reported(monkeypatch, status):
    async def fail(data, content_type):
        raise _HTTPException(status, "ocr says no")

    monkeypatch.setattr(_ocr, "request_ocr_lines", fail)
    resp = _post_image(_png())
    assert resp.status_code == status and resp.json() == {"error": "ocr says no"}


def test_image_to_words_multiline_box_gets_fitted_font_and_no_overlap(monkeypatch):
    long = "**GREEN BOWL** steamed & raw vegetables, quinoa, avocado, poached egg, tahini dressing and toasted seeds"
    _fake_ocr(
        monkeypatch,
        [
            {"text": long, "bbox": [58, 100, 520, 150]},
            {"text": "26", "bbox": [500, 100, 540, 118]},
            {"text": "next dish", "bbox": [58, 152, 300, 170]},
        ],
    )
    doc = _docx_of(_post_image(_png()))
    frames = {f[0]: f for f in _frames(doc)}
    assert "**" not in "".join(frames)
    desc = next(f for f in frames.values() if f[0].startswith("GREEN BOWL"))
    price = frames["26"]
    assert desc[1] + desc[3] <= price[1]  # left text stops before the right text starts
    sizes = {int(r.get(_W + "val")) / 2 for r in doc.element.body.iter(_W + "sz")}
    assert max(sizes) < 18  # not the ~28pt a 50px-tall box would give a single line
    ordered = sorted(frames.values(), key=lambda f: f[2])
    for a, b in zip(ordered, ordered[1:]):
        if a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
            assert a[2] + a[4] <= b[2] + 0.5


def test_image_to_words_bold_markdown_becomes_bold_run(monkeypatch):
    _fake_ocr(monkeypatch, [{"text": "**BUTTER** churned", "bbox": [58, 83, 300, 107]}])
    doc = _docx_of(_post_image(_png()))
    assert len(list(doc.element.body.iter(_W + "b"))) == 1
    assert _frames(doc)[0][0] == "BUTTER churned"


def test_image_to_words_clamped_tail_keeps_rows_prices_and_indents(monkeypatch):
    """The model clamps everything past the page bottom to y=826 (real page-5 log): x is still good."""
    _fake_ocr(
        monkeypatch,
        [
            {"text": "**ZHOUG** coriander, jalapeno,", "bbox": [58, 793, 204, 809]},
            {"text": "5", "bbox": [524, 793, 541, 809]},
            {"text": "**BUTTER** churned from New Zealand", "bbox": [58, 818, 262, 826]},
            {"text": "5", "bbox": [506, 818, 524, 826]},
            {"text": "A BIT SWEET...", "bbox": [58, 826, 192, 826]},
            {"text": "**FRENCH TOAST** strawberries and cream, sablè", "bbox": [58, 826, 262, 826]},
            {"text": "24", "bbox": [506, 826, 524, 826]},
            {"text": "+ VANILLA ICE CREAM", "bbox": [116, 826, 233, 826]},
            {"text": "+5", "bbox": [506, 826, 524, 826]},
        ],
    )
    frames = {f[0]: f for f in _frames(_docx_of(_post_image(_png(582, 826), "p.png")))}
    k = 0.75
    toast = next(f for f in frames.values() if f[0].startswith("FRENCH TOAST"))
    price, addon, addon_price = frames["24"], frames["+ VANILLA ICE CREAM"], frames["+5"]
    butter = next(f for f in frames.values() if f[0].startswith("BUTTER"))
    assert abs(price[2] - toast[2]) < 0.1 and abs(addon_price[2] - addon[2]) < 0.1  # price shares its row
    assert price[1] == round(506 * k, 2) and addon[1] == 116 * k  # own x, not the left margin
    assert butter[4] > 10  # not squashed to the 8 px the model gave it
    ys = [frames["A BIT SWEET..."][2], toast[2], addon[2]]
    assert ys == sorted(ys) and len(set(ys)) == 3
    assert butter[2] > next(f for f in frames.values() if f[0].startswith("ZHOUG"))[2]


# --- /image-to-words: ruled tables -----------------------------------------------------------

from PIL import ImageDraw as _ImageDraw

_GRID_XS, _GRID_YS = (50, 250, 400, 550), (100, 160, 220, 280)
# (row, first col, last col + 1, inked): row 0 has a cell spanning the first two columns
_GRID_CELLS = [(0, 0, 2, True), (0, 2, 3, True), (1, 0, 1, True), (1, 1, 2, True), (1, 2, 3, True),
               (2, 0, 1, True), (2, 1, 2, False), (2, 2, 3, True)]


def _glyphs(draw, x: int, y: int, n: int) -> None:
    """n glyph-like strokes: narrow, so they are text ink rather than ruling."""
    for i in range(n):
        draw.rectangle([x + 10 * i, y, x + 10 * i + 5, y + 8], fill="#333")


def _ruled_png() -> bytes:
    """600x400 white image: a ruled 3x3 grid (merged top-left cell) with a dark block of "text" in
    every inked cell, and a heading above the grid."""
    image = Image.new("RGB", (600, 400), "white")
    draw = _ImageDraw.Draw(image)
    _glyphs(draw, 60, 30, 12)  # heading
    for x in _GRID_XS:
        draw.line([(x, _GRID_YS[0]), (x, _GRID_YS[-1])], fill="black", width=3)
    for y in _GRID_YS:
        draw.line([(_GRID_XS[0], y), (_GRID_XS[-1], y)], fill="black", width=3)
    draw.rectangle([250 - 1, 101, 250 + 1, 159], fill="white")  # erase the line inside the merged cell
    for r, c0, c1, inked in _GRID_CELLS:
        if inked:
            _glyphs(draw, _GRID_XS[c0] + 15, _GRID_YS[r] + 25, 10)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _fake_table_ocr(monkeypatch, page_lines, row_lines):
    """The page call (an image of the upload's size) gets page_lines; each table-row call pops the
    next entry of row_lines: a list of lines (crop pixels) or an exception to raise."""
    calls = []

    async def fake(data, content_type):
        with Image.open(io.BytesIO(data)) as image:
            size = image.size
        calls.append(size)
        if size == (600, 400):
            return page_lines
        result = row_lines.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(_ocr, "request_ocr_lines", fake)
    return calls


def _cell_texts(doc) -> list[list[str]]:
    assert len(doc.tables) == 1
    return [[cell.text for cell in row.cells] for row in doc.tables[0].rows]


def _row(*texts):
    """Row-crop lines, left to right; their boxes are deliberately vague (the order decides)."""
    return [{"text": t, "bbox": [10 + 300 * i, 5, 200 + 300 * i, 40]} for i, t in enumerate(texts)]


def test_image_to_words_ruled_grid_becomes_word_table_read_row_by_row(monkeypatch):
    page = [
        {"text": "Lunch", "bbox": [60, 30, 300, 55]},
        {"text": "Noodles", "bbox": [400, 230, 500, 250]},  # page boxes are wrong inside the table ...
        {"text": "190", "bbox": [60, 120, 100, 140]},  # ... and the "Rice" row is missing entirely
    ]
    rows = [_row("Menu", "Price"), _row("Noodles", "S", "190"), _row("Rice", "220")]
    calls = _fake_table_ocr(monkeypatch, page, rows)
    doc = _docx_of(_post_image(_ruled_png()))
    assert _cell_texts(doc) == [["Menu", "Menu", "Price"], ["Noodles", "S", "190"], ["Rice", "", "220"]]
    assert [f[0] for f in _frames(doc)] == ["Lunch"]  # table text is not repeated as frames
    assert len(calls) == 4 and all(w > 600 and h < 400 for w, h in calls[1:])  # upscaled one-row crops
    assert len(list(doc.element.body.iter(_W + "gridSpan"))) == 1


def test_image_to_words_table_row_ocr_failure_falls_back_to_page_lines(monkeypatch):
    page = [
        {"text": "Menu", "bbox": [60, 120, 150, 140]},
        {"text": "Price", "bbox": [410, 120, 480, 140]},
        {"text": "Rice", "bbox": [60, 240, 120, 260]},
        {"text": "220", "bbox": [410, 240, 460, 260]},
    ]
    error = _HTTPException(502, "ocr service unavailable")
    _fake_table_ocr(monkeypatch, page, [[], _row("Noodles", "S", "190"), error])
    texts = _cell_texts(_docx_of(_post_image(_ruled_png())))
    assert texts == [["Menu", "Menu", "Price"], ["Noodles", "S", "190"], ["Rice", "", "220"]]


def test_image_to_words_merged_row_line_is_split_across_cells(monkeypatch):
    # one line read across the whole row crop (x 16..1016 in the 2x crop = image x 50..550); the
    # per-cell reads that follow fail, so the split is what's left
    merged = [{"text": "Noodles S 190", "bbox": [16, 5, 1016, 40]}]
    error = _HTTPException(502, "ocr service unavailable")
    _fake_table_ocr(monkeypatch, [], [_row("Menu", "Price"), merged, error, error, error, _row("Rice", "220")])
    texts = _cell_texts(_docx_of(_post_image(_ruled_png())))
    assert texts[1] == ["Noodles", "S", "190"]


def test_image_to_words_mismatched_row_is_read_cell_by_cell(monkeypatch):
    def cell(*pieces):  # pieces of one visual line, left to right, in the 2x cell crop
        return [{"text": t, "bbox": [10 + 60 * i, 10, 50 + 60 * i, 40]} for i, t in enumerate(pieces)]

    rows = [_row("Menu", "Price"), _row("Noodles S", "190"), cell("Nood", "les"), cell("S"), [], _row("Rice", "220")]
    calls = _fake_table_ocr(monkeypatch, [], rows)
    doc = _docx_of(_post_image(_ruled_png()))
    # the row read paired 2 lines with 3 cells: each cell was read alone; "Nood" + "les" joined on
    # one line; the empty read of the last cell kept the row read's guess
    assert _cell_texts(doc)[1] == ["Nood les", "S", "190"]
    assert len(calls) == 7 and rows == []


def test_image_to_words_doubtful_page_line_already_in_table_is_dropped(monkeypatch):
    # collapsed boxes: "Rice 220" is in the table (over two cells), so only "Footer note" is stacked
    page = [{"text": "Rice 220", "bbox": [60, 400, 120, 400]}, {"text": "Footer note", "bbox": [60, 400, 200, 400]}]
    _fake_table_ocr(monkeypatch, page, [_row("Menu", "Price"), _row("Noodles", "S", "190"), _row("Rice", "220")])
    doc = _docx_of(_post_image(_ruled_png()))
    assert [f[0] for f in _frames(doc)] == ["Footer note"]


# --- /giveme-suggestion-image ------------------------------------------------------------------


def _post_suggest_image(monkeypatch, lines, suggestions, data=None, summary="Try the salad."):
    seen = {}

    async def fake_highlight(data_, content_type, phrases):
        seen["phrases"] = phrases
        return b"\x89PNG highlighted"

    async def fake_suggestions(instruction_, texts):
        seen["texts"] = texts
        return suggestions

    async def fake_summary(instruction_, highlights):
        return summary

    _fake_ocr(monkeypatch, lines)
    monkeypatch.setattr(_ocr, "request_highlight", fake_highlight)
    monkeypatch.setattr("app.client.translator.request_suggestions", fake_suggestions)
    monkeypatch.setattr("app.client.translator.request_summary", fake_summary)
    res = client.post(
        "/giveme-suggestion-image",
        files={"file": ("menu.png", _png() if data is None else data, "image/png")},
        data={"instruction": "something light"},
    )
    res.seen = seen
    return res


def test_giveme_suggestion_image_streams_highlighted_png_then_summary(monkeypatch):
    import json

    lines = [{"text": "Garden salad", "bbox": [20.4, 40, 140, 60]}, {"text": "Fried rice", "bbox": [20, 70, 120, 90]}]
    res = _post_suggest_image(monkeypatch, lines, [{"line": 0, "start": 7, "end": 12}])
    assert res.status_code == 200
    (file_headers, file_body), (_, json_body) = _multipart_parts(res)
    assert file_headers["Content-Type"] == "image/png"
    assert "suggested-menu.png" in file_headers["Content-Disposition"]
    assert file_body == b"\x89PNG highlighted"
    assert json.loads(json_body) == {"summary": "Try the salad.", "highlights": ["salad"]}
    assert res.seen["texts"] == ["Garden salad", "Fried rice"]
    assert res.seen["phrases"] == [{"line_text": "Garden salad", "line_bbox": [20, 40, 140, 60], "start": 7, "end": 12}]


def test_giveme_suggestion_image_error_cases(monkeypatch):
    lines = [{"text": "Garden salad", "bbox": [20, 40, 140, 60]}]
    assert _post_suggest_image(monkeypatch, [{"text": " ", "bbox": [0, 0, 1, 1]}], []).status_code == 422
    assert _post_suggest_image(monkeypatch, lines, []).status_code == 404
    assert _post_suggest_image(monkeypatch, lines, [{"line": 4, "start": 0, "end": 1}]).status_code == 404
    assert _post_suggest_image(monkeypatch, lines, [], data=b"not an image").status_code == 400
    assert _post_suggest_image(monkeypatch, lines, [], data=b"").status_code == 400
