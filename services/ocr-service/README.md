# ocr-service

Minimal FastAPI wrapper around [mlx-vlm](https://github.com/Blaizzy/mlx-vlm) that prompts a
vision-language model (default `mlx-community/Qwen3-VL-8B-Instruct-4bit`) to read the text in an image, line by
line, with bounding boxes. Apple Silicon (MLX) only — this service does not run on Linux/Intel or in
typical CI.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Download the model manually (not fetched automatically at runtime):

```bash
uv run hf download mlx-community/Qwen3-VL-8B-Instruct-4bit \
  --local-dir models/Qwen3-VL-8B-Instruct-4bit
```

Pick the model with `OCR_MODEL` (default `Qwen3-VL-8B-Instruct-4bit`, the best performer). Allowed
values: `Qwen3-VL-8B-Instruct-4bit`, `Qwen3.5-4B-MLX-8bit`, `NuExtract3-mlx-8bits`; any other value fails
at startup. The directory `models/<OCR_MODEL>` must exist, so download the others only if you want to
switch. Override the path entirely with `OCR_MODEL_PATH` (not validated).

## Run

```bash
cd services/ocr-service
uv run uvicorn app.main:app --host 127.0.0.1 --port 8004 --log-level debug --reload
```

```bash
curl http://localhost:8004/health
```

## API

`POST /analyze` — body is the raw image binary.

```bash
curl -X POST --data-binary @sample.png -H 'Content-Type: image/png' http://localhost:8004/analyze
```

```json
[
  { "text": "Exit", "bbox": [120, 40, 310, 88] },
  { "text": "Platform 3", "bbox": [118, 100, 402, 150] }
]
```

- One entry per visual text line, in reading order.
- `bbox` is `[x1, y1, x2, y2]` in image pixels, top-left origin.
- Errors are `{ "error": "..." }`: 400 for an empty, oversized (`OCR_MAX_IMAGE_BYTES`, default 10 MB) or
  non-image body; 503 while the model loads; 500 if inference fails.

`POST /highlight` — multipart: `file` (the image) and `phrases` (JSON). Returns the image as PNG with
each phrase covered by a translucent highlight.

```bash
curl -F file=@menu.png \
  -F 'phrases=[{"line_text": "Garden salad", "line_bbox": [118, 100, 402, 150], "start": 7, "end": 12}]' \
  http://localhost:8004/highlight -o highlighted.png -D -
```

- Each phrase is the `[start, end)` chars of one `/analyze` line (`line_text`, `line_bbox`).
- The model is asked where each phrase is (one extra generation over the whole list). A phrase it doesn't
  find, or places off its own line (vertical centre outside the line box padded by half its height), is
  estimated instead: the line box sliced by char position.
- The boxes used are in the `X-Highlight-Boxes` response header: `[{"bbox": [x1, y1, x2, y2], "source":
  "located" | "estimated"}]`.
- Config: `OCR_HIGHLIGHT_COLOR` (RGBA, default `255,230,0,110`), `OCR_HIGHLIGHT_LOCATE` (`0` skips the model
  call and estimates every box — also the switch to use when the model's boxes are poor).
- Errors as `/analyze`, plus 400 for malformed `phrases` (empty list, bad bbox, or a range outside its line).
- Note: NuExtract3 is fine-tuned for document extraction (its chat template wraps the prompt as document
  content), so locating a given phrase is best effort; check the `source` tags to judge it.

## Known risk: boxes are model-estimated

The model emits coordinates normalized to 0–1000, which the service scales to pixels. Text is usually
good; boxes are approximate (not pixel-exact like a dedicated OCR engine), and very dense pages may be
truncated at `OCR_MAX_TOKENS` (default 8192) — complete lines before the cut are still returned.
Set `OCR_LOG_LEVEL=DEBUG` to log the raw model output and parsed lines.

On a tall image where the model stops before the bottom, `/analyze` makes up to `OCR_CONTINUE_MAX`
(default 3, `0` = off) extra passes on the unread part, as long as it is taller than
`OCR_CONTINUE_MIN_RATIO` (default 0.1) of the image.

Images whose long side is under `OCR_MIN_LONG_SIDE` (default 1600, `0` = off) are upscaled before
inference: a small, dense image (a phone photo of a menu) gives the model too few vision tokens per
glyph and it starts skipping lines. Boxes are normalized, so they are still returned in the original
image's pixels.

## Tests

```bash
uv run pytest
```

Uses a fake engine, so no model download is needed.
