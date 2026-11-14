import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main, state
from app.engine.ocr_engine.boxes import estimate_box, resolve_boxes
from app.engine.ocr_engine.parse import parse_located, parse_lines
from app.feature.common import upright


class FakeEngine:
    seen_size = None  # size of the image file the model was given

    def analyze(self, image_path, width, height, part=""):
        assert (width, height) == (200, 100)
        with Image.open(image_path) as image:
            FakeEngine.seen_size = image.size
        return [{"text": "hello", "bbox": [1, 2, 3, 4]}]

    located = []  # what locate returns; set per test
    seen_phrases = None

    def locate(self, image_path, width, height, phrases):
        FakeEngine.seen_phrases = phrases
        return FakeEngine.located


def png_bytes(size=(200, 100)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format="PNG")
    return buf.getvalue()


def jpeg_bytes(size, orientation=None) -> bytes:
    buf = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    Image.new("RGB", size, "white").save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    # Skip lifespan (it would load the real MLX model); inject the fake engine directly.
    monkeypatch.setattr(state, "engine", FakeEngine())
    monkeypatch.setattr("app.feature.analyze.CONTINUE_MAX", 0)  # FakeEngine only reads whole 200x100 images
    return TestClient(main.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "model_loaded": True}


def test_analyze_returns_lines(client):
    res = client.post("/analyze", content=png_bytes(), headers={"Content-Type": "image/png"})
    assert res.status_code == 200
    assert res.json() == [{"text": "hello", "bbox": [1, 2, 3, 4]}]


def test_analyze_turns_exif_rotated_photo_upright(client, monkeypatch):
    # Stored 100x200, shown rotated 90 degrees: the model and the boxes both work in 200x100.
    monkeypatch.setattr("app.feature.common.MIN_LONG_SIDE", 0)
    res = client.post("/analyze", content=jpeg_bytes((100, 200), 6), headers={"Content-Type": "image/jpeg"})
    assert res.status_code == 200  # FakeEngine asserts it was told 200x100
    assert FakeEngine.seen_size == (200, 100)


def test_upright_turns_only_rotated_images():
    with Image.open(io.BytesIO(upright(jpeg_bytes((100, 200), 6)))) as image:
        assert (image.format, image.size) == ("PNG", (200, 100))
    assert upright(jpeg_bytes((100, 200), 1)) is None
    assert upright(jpeg_bytes((100, 200))) is None
    assert upright(b"not an image") is None


def test_analyze_upscales_small_image_but_keeps_original_pixel_space(client, monkeypatch):
    monkeypatch.setattr("app.feature.common.MIN_LONG_SIDE", 1600)
    res = client.post("/analyze", content=png_bytes(), headers={"Content-Type": "image/png"})
    assert res.status_code == 200
    assert FakeEngine.seen_size == (1600, 800)  # the engine is still told 200x100, see FakeEngine


def test_analyze_large_enough_image_is_not_resized(client, monkeypatch):
    monkeypatch.setattr("app.feature.common.MIN_LONG_SIDE", 0)
    client.post("/analyze", content=png_bytes(), headers={"Content-Type": "image/png"})
    assert FakeEngine.seen_size == (200, 100)


class PassesEngine:
    """Returns the next scripted pass of lines on each analyze call, and records the sizes it was told."""

    def __init__(self, *passes):
        self.passes = list(passes)
        self.sizes = []

    def analyze(self, image_path, width, height, part=""):
        self.sizes.append((width, height))
        return self.passes.pop(0) if self.passes else []


def analyze_with(monkeypatch, engine, size=(200, 100)):
    monkeypatch.setattr(state, "engine", engine)
    monkeypatch.setattr("app.feature.common.MIN_LONG_SIDE", 0)
    res = TestClient(main.app).post("/analyze", content=png_bytes(size), headers={"Content-Type": "image/png"})
    assert res.status_code == 200
    return res.json()


def test_analyze_continues_below_where_the_model_stopped(monkeypatch):
    engine = PassesEngine(
        [{"text": "1 noodles", "bbox": [0, 10, 80, 20]}, {"text": "220", "bbox": [90, 10, 120, 20]},
         {"text": "5 soup", "bbox": [0, 25, 80, 35]}],
        # Crop starts at y=25 (the last row): its price is new, "5 soup" again is a duplicate.
        [{"text": "5 soup", "bbox": [0, 0, 80, 10]}, {"text": "100", "bbox": [90, 1, 120, 10]},
         {"text": "12 pork dumplings", "bbox": [0, 30, 80, 40]}, {"text": "220", "bbox": [90, 30, 120, 40]}],
    )
    lines = analyze_with(monkeypatch, engine)
    assert engine.sizes == [(200, 100), (200, 75), (200, 45)]
    assert lines == [
        {"text": "1 noodles", "bbox": [0, 10, 80, 20]},
        {"text": "220", "bbox": [90, 10, 120, 20]},
        {"text": "5 soup", "bbox": [0, 25, 80, 35]},
        {"text": "100", "bbox": [90, 26, 120, 35]},
        {"text": "12 pork dumplings", "bbox": [0, 55, 80, 65]},
        {"text": "220", "bbox": [90, 55, 120, 65]},  # same price as item 1, but on another row
    ]


def test_analyze_does_not_continue_when_lines_reach_the_bottom(monkeypatch):
    engine = PassesEngine([{"text": "end", "bbox": [0, 85, 80, 95]}])
    analyze_with(monkeypatch, engine)
    assert engine.sizes == [(200, 100)]


def test_analyze_does_not_continue_on_a_one_row_crop(monkeypatch):
    engine = PassesEngine([{"text": "15全筋湯", "bbox": [0, 15, 80, 70]}])  # 30px below, the line is 55px tall
    analyze_with(monkeypatch, engine)
    assert engine.sizes == [(200, 100)]


def test_analyze_continue_can_be_turned_off(monkeypatch):
    monkeypatch.setattr("app.feature.analyze.CONTINUE_MAX", 0)
    engine = PassesEngine([{"text": "top", "bbox": [0, 0, 80, 10]}])
    analyze_with(monkeypatch, engine)
    assert engine.sizes == [(200, 100)]


def test_analyze_stops_continuing_when_a_pass_adds_nothing(monkeypatch):
    engine = PassesEngine([{"text": "top", "bbox": [0, 0, 80, 10]}], [{"text": "top", "bbox": [0, 0, 80, 10]}])
    assert analyze_with(monkeypatch, engine) == [{"text": "top", "bbox": [0, 0, 80, 10]}]
    assert engine.sizes == [(200, 100), (200, 100)]


def test_analyze_empty_body(client):
    res = client.post("/analyze", content=b"")
    assert res.status_code == 400
    assert "error" in res.json()


def test_analyze_not_an_image(client):
    res = client.post("/analyze", content=b"not an image")
    assert res.status_code == 400


def test_analyze_model_not_loaded(monkeypatch):
    monkeypatch.setattr(state, "engine", None)
    res = TestClient(main.app).post("/analyze", content=png_bytes())
    assert res.status_code == 503


def test_parse_lines_scales_to_pixels():
    raw = '[{"text": "Hi", "bbox_2d": [100, 200, 500, 300]}]'
    assert parse_lines(raw, 200, 100) == [{"text": "Hi", "bbox": [20, 20, 100, 30]}]


def test_parse_lines_handles_fences_and_think():
    raw = '<think>hmm</think>```json\n[{"text": "A", "bbox_2d": [0, 0, 1000, 1000]}]\n```'
    assert parse_lines(raw, 50, 40) == [{"text": "A", "bbox": [0, 0, 50, 40]}]


def test_parse_lines_salvages_truncated_output():
    raw = '[{"text": "A", "bbox_2d": [0, 0, 10, 10]}, {"text": "B", "bbox_2d": [0, 2'
    assert [l["text"] for l in parse_lines(raw, 1000, 1000)] == ["A"]


def test_parse_lines_clamps_and_drops_malformed():
    raw = '[{"text": "A", "bbox_2d": [-50, 0, 1200, 10]}, {"text": "", "bbox_2d": [0,0,1,1]}, {"text": "C"}]'
    assert parse_lines(raw, 100, 100) == [{"text": "A", "bbox": [0, 0, 100, 1]}]


# --- /highlight --------------------------------------------------------------------------------

import json

LINE = {"line_text": "Garden salad", "line_bbox": [20, 40, 140, 60], "start": 7, "end": 12}  # "salad"


def post_highlight(client, phrases, image=None):
    return client.post(
        "/highlight",
        files={"file": ("menu.png", image if image is not None else png_bytes(), "image/png")},
        data={"phrases": phrases if isinstance(phrases, str) else json.dumps(phrases)},
    )


def test_highlight_uses_located_box_on_its_line(client):
    FakeEngine.located = [[80, 42, 130, 58]]
    res = post_highlight(client, [LINE])
    assert res.status_code == 200 and res.headers["content-type"] == "image/png"
    assert FakeEngine.seen_phrases == ["salad"]
    assert json.loads(res.headers["x-highlight-boxes"]) == [{"bbox": [80, 42, 130, 58], "source": "located"}]
    with Image.open(io.BytesIO(res.content)) as image:
        assert image.size == (200, 100)
        assert image.getpixel((100, 50)) != (255, 255, 255)  # inside: tinted
        assert image.getpixel((10, 10)) == (255, 255, 255)  # outside: untouched


def test_highlight_estimates_missing_or_off_line_boxes(client):
    FakeEngine.located = [None, [0, 80, 50, 95]]  # not found / found on another line
    res = post_highlight(client, [LINE, LINE])
    boxes = json.loads(res.headers["x-highlight-boxes"])
    assert [b["source"] for b in boxes] == ["estimated", "estimated"]
    assert boxes[0]["bbox"] == estimate_box([20, 40, 140, 60], "Garden salad", 7, 12)


def test_highlight_without_locate_skips_the_model(client, monkeypatch):
    monkeypatch.setattr("app.feature.highlight.HIGHLIGHT_LOCATE", False)
    FakeEngine.seen_phrases = None
    res = post_highlight(client, [LINE])
    assert res.status_code == 200
    assert FakeEngine.seen_phrases is None
    assert json.loads(res.headers["x-highlight-boxes"])[0]["source"] == "estimated"


def test_highlight_400_cases(client):
    assert post_highlight(client, [LINE], image=b"").status_code == 400
    assert post_highlight(client, [LINE], image=b"not an image").status_code == 400
    assert post_highlight(client, "not json").status_code == 400
    assert post_highlight(client, []).status_code == 400
    assert post_highlight(client, [{**LINE, "end": 99}]).status_code == 400
    assert post_highlight(client, [{**LINE, "line_bbox": [1, 2]}]).status_code == 400


def test_highlight_model_not_loaded(monkeypatch):
    monkeypatch.setattr(state, "engine", None)
    assert post_highlight(TestClient(main.app), [LINE]).status_code == 503


def test_estimate_box_slices_line_by_char_position():
    assert estimate_box([0, 10, 100, 20], "abcdefghij", 2, 5) == [20, 10, 50, 20]


def test_resolve_boxes_accepts_located_box_near_its_line():
    phrase = {"line_bbox": [0, 100, 100, 120], "line_text": "abcd", "start": 0, "end": 2}
    assert resolve_boxes([phrase], [[0, 95, 40, 125]])[0]["source"] == "located"
    assert resolve_boxes([phrase], [[0, 200, 40, 220]])[0]["source"] == "estimated"


def test_parse_located_maps_ids_to_pixel_boxes():
    raw = (
        '<think>x</think>```json\n[{"id": 1, "bbox_2d": [100, 200, 500, 300]}, '
        '{"id": 7, "bbox_2d": [0, 0, 10, 10]}, {"id": 0, "bbox_2d": [5, 5, 5, 9]}, {"id": 0, "bbox_2d": [0, 2'
    )
    # id 7 out of range, id 0's box is empty (x1 == x2 after scaling), the tail is truncated
    assert parse_located(raw, 2, 200, 100) == [None, [20, 20, 100, 30]]

