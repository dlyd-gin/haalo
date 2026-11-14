# document-service

FastAPI service for documents: PDFs (via [pdfplumber](https://github.com/jsvine/pdfplumber)), Word
(.docx) files, and images of pages (via ocr-service). Its `/analyze` endpoint reports, per page, whether a PDF page has a text layer, a table, an
image, a header, and/or a footer, plus a best-effort printed page number. Useful for routing pages
downstream (e.g. deciding which pages need OCR vs. can be text-extracted directly) or reconciling a
document's printed page numbering against its physical page order.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

No model download needed — this service is pure Python (no ML model). Some endpoints call sibling
services, which must be running for them: `/image-to-words` and `/giveme-suggestion-image` need
`ocr-service` (`DOC_OCR_URL`, port 8004), and `/ground-state` and the `/giveme-suggestion*` endpoints need
`translator-service` (`DOC_TRANSLATOR_URL`, port 8001).

## Run

From the repo root:

```bash
cd services/document-service
uv run uvicorn app.main:app --host 127.0.0.1 --port 8003 --log-level debug --reload
```

Confirm it's up:

```bash
curl http://localhost:8003/health
```

Note: uvicorn's own `--log-level debug` only affects uvicorn's request logs, not this app's internal
debug logging (e.g. which `printed_page` rule matched). Set `DOC_LOG_LEVEL=DEBUG` to see that:

```bash
DOC_LOG_LEVEL=DEBUG uv run uvicorn app.main:app --host 127.0.0.1 --port 8003 --reload
```

## API

`POST /analyze`

```bash
curl -X POST "http://localhost:8003/analyze" \
  --data-binary @document.pdf \
  -H "Content-Type: application/pdf"
```

Takes the raw PDF bytes as the request body (no multipart) and returns a JSON summary:

```json
{
  "page_count": 3,
  "pages": [
    {"page": 1, "has_text": true, "has_table": false, "has_image": true,
     "has_header": false, "has_footer": true, "printed_page": "1"},
    {"page": 2, "has_text": true, "has_table": true, "has_image": false,
     "has_header": true, "has_footer": true, "printed_page": "Page 2 of 3"},
    {"page": 3, "has_text": false, "has_table": false, "has_image": false,
     "has_header": false, "has_footer": false, "printed_page": ""}
  ]
}
```

- `has_text`: the page has an extractable text layer (a scanned/image-only page has none)
- `has_table`: pdfplumber's table-detection heuristic found at least one table on the page
- `has_image`: the page contains at least one embedded image
- `has_header` / `has_footer`: the page has any text within the top / bottom margin band
  (`DOC_MARGIN_RATIO` env var, default 10% of page height)
- `printed_page`: the page number as printed in the header or footer, including any surrounding
  context (e.g. `"12"`, `"Page 2 of 3"`, `"Annex 1 - Page 3"`), or `""` if none was confidently
  found — see "Known limitation" below

An empty request body or a PDF that fails to parse returns a 400 with `{"error": "..."}`.

## Known limitation: `printed_page` is a heuristic

`printed_page` looks for plain digit sequences and roman numerals (e.g. `"12"` or `"iv"`/`"XII"`)
found within the top or bottom margin band. Roman numerals are validated structurally (e.g. `"IX"` =
9 is accepted, but a word merely *made of* the letters i/v/x/l/c/d/m like "civil" or "mild" is
rejected) — the one accepted residual risk is a word that's coincidentally also a valid numeral, e.g.
"mix" (M + IX = 1009). **The header is checked first**: if the header has a usable match, it's used
and the footer is not consulted at all; only when the header has none does a footer match get used.

Within whichever band is used, a line containing the word "page" (case-insensitive, optionally with
trailing `:`/`.`/`,`) immediately followed by a digit or roman numeral wins outright, **even from the
left third of the page**, since an explicit label is a stronger signal than position — and the full
matched phrase is returned verbatim, not just the bare number:

- `"Page 12"` → `"Page 12"`
- `"Page 3 of 45"` → `"Page 3 of 45"` (the trailing `"of TOTAL"` fraction is included)
- `"Annex 1 - Page 3"` → `"Annex 1 - Page 3"` (a leading section label plus an identifier, joined to
  the page reference by a dash, comma, colon, "of", or just whitespace, is included)
- `"Annex 1 of Page 1"` → `"Annex 1 of Page 1"`
- `"Schedule B, Page 4"` → `"Schedule B, Page 4"`
- `"Vol. II - Page 7"` → `"Vol. II - Page 7"`

The section label isn't limited to "Annex" — it recognizes the standard set of document-structure
reference words (and their common abbreviations) found across legal, technical, and regulatory
documents: Annex/Annexure, Appendix/Appendices (App), Schedule (Sched), Exhibit, Attachment (Att),
Enclosure (Encl), Addendum, Supplement (Supp), Section (Sec), Chapter (Ch), Article (Art),
Paragraph (Para), Clause, Part, Tab, Volume (Vol), Module, Unit, Table, and Figure (Fig). This is a
curated list of conventional labels, not a fully generic match on any preceding word — an arbitrary
word before a number would otherwise risk being mistaken for a label.

This label match requires "page" and the number to be on the same line (words can wrap across
multiple lines within the band, but "page" and its number can't); if they don't share a line, this
rule doesn't fire and horizontal-position selection (below) is used instead, returning just the bare
token. "Same line" is judged by vertical bounding-box overlap, not raw text position alone, so a
short glyph like a hyphen or comma (whose bounding box is much shallower than the letters around
it) doesn't get misjudged as being on its own line and split off from the label — the full phrase
is returned rather than a truncated piece of it (e.g. "Annex A - Page 2" rather than just "Page 2").

Otherwise, a bare digit/roman-numeral candidate is only trusted if its line has at most 3 words
total — a number embedded in running prose (e.g. a wrapped header/title like "...over the 10 Year
capital plan...") is discarded rather than mistaken for a page number, even if it lands in the
center/right zone. Numbers on a short, mostly-decorative line (e.g. `"- 12 -"`, `"12 |"`) still
count. Among the surviving candidates, position decides: one in the **right** third of the page
width wins; if none, one in the **center** third is used; a candidate found only in the **left**
third of the page is not treated as a page number at all (this is the convention for
bottom-right/top-right and bottom-center/top-center page numbers — a left-aligned number is more
likely a document code, chapter marker, or similar). If multiple candidates remain in the same
zone (e.g. two lines within the band), the one closest to that band's outer edge wins, with the
rightmost as a final tie-break. In this fallback path only the bare token is returned (no surrounding
context), since there's no "page" label tying it to a phrase.

Text that happens to be a bare number (or valid-looking roman numeral) for an unrelated reason (a
document code, a revision number) can still be reported as `printed_page` if it's preceded by the
word "page" or lands in the right or center zone, since there's no way to distinguish intent from
position and content alone.

`POST /extract-text`

```bash
curl -X POST "http://localhost:8003/extract-text" \
  -F "file=@document.pdf;type=application/pdf" \
  -F "pages=1" -F "pages=3" \
  -F "batch_size=2"
```

Takes the PDF as `multipart/form-data` (not raw bytes, unlike `/analyze`, since it also needs to
carry the params below in the body):

- `file`: the PDF to extract text from
- `pages`: optional, repeated form field of 1-indexed page numbers to extract (e.g. `-F "pages=1"
  -F "pages=3"`); omitted entirely = every page
- `batch_size`: optional, max number of pages parsed concurrently (`DOC_BATCH_SIZE` env var,
  default 4) — each page is parsed independently on its own thread, so this bounds both
  parallelism and peak memory use for large PDFs
- `x_tolerance_ratio`: optional override for the word-gap threshold (see "Known limitation" below);
  omitted = auto-calibrated per page

`bbox` (all text on the page) and each line's `bbox` are `[x0, top, x1, bottom]` in PDF points,
origin top-left; `lines` are in the same order as `text`. `bbox` is `null` and `lines` empty for a page
without text. Widely separated segments on one line (a horizontal gap above `DOC_GAP_FACTOR` × word
height, default 2.5) are joined by `DOC_GAP_SEPARATOR`.

Returns:

```json
{
  "page_count": 3,
  "pages": [
    {"page": 1, "text": "...", "bbox": [x0, top, x1, bottom],
     "lines": [{"text": "...", "bbox": [x0, top, x1, bottom]}], "x_tolerance_ratio": 0.18},
    {"page": 3, "text": "...", "x_tolerance_ratio": 0.2}
  ]
}
```

`x_tolerance_ratio` in each page result is the threshold actually used for that page, included for
transparency/debugging.

An empty file, invalid PDF, `batch_size` below 1, `x_tolerance_ratio` at or below 0, or a page
number outside `1..page_count` returns a 400 with `{"error": "..."}`.

### Known limitation: word-gap detection is calibrated, not exact

Some PDF generators — especially justified body text — render inter-word spacing as a small
position adjustment rather than an actual space glyph. pdfplumber decides word boundaries by
checking whether the gap between two characters exceeds a threshold expressed as a fraction of
character size (`x_tolerance_ratio`); a single fixed value doesn't fit every document (fonts and
generators vary in how tight their natural letter-kerning is relative to a real word gap), so by
default each page's own character spacing is used to estimate an appropriate threshold — the
natural separation point between within-word kerning gaps and between-word gaps on that specific
page. A page with too little text to calibrate confidently (e.g. a title page, or a page that's
mostly an image) falls back to a fixed default (`DOC_X_TOLERANCE_RATIO_FALLBACK` env var, default
0.2). If a particular page's output still isn't fully space-separated, pass `x_tolerance_ratio`
explicitly to override calibration for that request.

## `POST /extract-tables`

```bash
curl -X POST "http://localhost:8003/extract-tables" \
  -F "file=@document.pdf;type=application/pdf" \
  -F "pages=2"
```

Takes the same multipart params as `/extract-text` (`file`, optional repeated `pages`, `batch_size`,
`x_tolerance_ratio`) and returns each page as Markdown: text around the tables in reading order, with
every table rendered inline as a GitHub-flavored Markdown table (first row = header).

```json
{
  "page_count": 3,
  "pages": [
    {"page": 2,
     "markdown": "Note: some figures may be rounded\n\n| Assumptions | |\n| --- | --- |\n| Buffer | -$1,850 |\n\nOur Recommendation of the ...",
     "tables": [{"markdown": "| Assumptions | |\n...", "bbox": [x0, top, x1, bottom]}]}
  ]
}
```

- Detection tries ruling lines first; only if none are found does it fall back to pdfplumber's
  text-alignment strategy (borderless tables), requiring at least 2 rows and 2 columns so ordinary
  prose isn't mistaken for a table.
- A table cell with more than 25 words is treated as a prose paragraph inside a ruled box (e.g. a
  commentary cell beside a small key/value grid): it's moved out of the table and emitted as text right
  after it.
- The whole page is covered. Text above a table and text beside it (same rows, outside its border) is
  written first, then the table, then its long prose cells and any text below. Words inside a
  table's border that fall in none of its cells (e.g. a header line drawn across the top of a boxed
  area) are emitted as plain text lines, above the table if they sit above its first row, otherwise
  after it. Coverage is decided by position, never by comparing text, so words that also occur in the
  table can't hide them. Each page reports `recovered_text: true` when this happened. A detected table
  that renders empty is ignored and its words come out as ordinary text.
- A page with text but no tables is still returned, with `tables: []` and `markdown` = its plain text.
- Pages with no text layer (scanned/image-only) are **not OCR'd** and are omitted from `pages`. If
  every requested page is like that, the response is **204 No Content** with an empty body.
- Same 400 `{"error": "..."}` cases as `/extract-text`.

Known limitation: merged cells, nested tables and multi-line headers are flattened to a single
Markdown grid, so spans are not preserved.

## `POST /extract-images`

```bash
curl -X POST "http://localhost:8003/extract-images" \
  -F "file=@document.pdf;type=application/pdf" \
  -F "pages=1"
```

Takes the same multipart params as `/extract-text` (`file`, optional repeated `pages`, `batch_size`;
no `x_tolerance_ratio`) and returns the images on each page. Every requested page is returned, with
`images: []` when it has none.

```json
{
  "page_count": 2,
  "pages": [
    {"page": 1, "images": [
      {"bbox": [20.0, 60.0, 70.0, 100.0], "type": "jpeg", "width_px": 1200, "height_px": 960,
       "dpi": [1728.0, 1728.0], "page_coverage": 0.05, "colorspace": "DeviceRGB"}
    ]},
    {"page": 2, "images": []}
  ]
}
```

- `bbox`: `[x0, top, x1, bottom]` in PDF points, origin top-left (same as `/extract-text`).
- `type`: from the image's compression filter: `jpeg`, `jpeg2000`, `jbig2`, `ccitt`, or `raw` for
  lossless/unfiltered pixel data (Flate/LZW/RunLength, which carry no file format of their own). Any
  other filter is reported as its lowercased name.
- `width_px` / `height_px`: the image's own pixel size.
- `dpi`: effective resolution as `[x, y]`: source pixels divided by the placed size in inches
  (`null` if the placed size is zero). Low values mean a low-resolution image.
- `page_coverage`: fraction (0-1) of the page area the image covers, clamped to the page.
- `colorspace`: e.g. `DeviceRGB`, `DeviceGray`, `ICCBased`, or `null`.

Same 400 `{"error": "..."}` cases as `/extract-text` (minus `x_tolerance_ratio`). Images are not
decoded or described: this reports where they are and what they are, not what they show.

## `POST /annotate-images`

```bash
curl -X POST "http://localhost:8003/annotate-images" \
  -F "file=@document.pdf;type=application/pdf" \
  -F "pages=1" -F "margin=6" -o page1.jpg
```

Same request payload as `/extract-images` (`file`, optional `pages`, `batch_size`) plus `margin`, but returns the
page as an `image/jpeg` file with a red rectangle drawn around each image `/extract-images` finds
(it reuses that detection). Handy for checking what was detected.

- One JPEG per response, so exactly one page is rendered: `pages` omitted means page 1; passing more
  than one page is a 400.
- A page with no images is returned as a plain render. The `X-Image-Count` header gives the number
  of boxes drawn; `Content-Disposition` names the file `page-N-annotated.jpg`.
- Fragments that touch or overlap (within 1pt) are boxed as one image: some PDFs draw a single
  picture as many thin strips, which `/extract-images` lists individually. So `X-Image-Count` can be
  lower than the number of entries `/extract-images` returns for the page.
- `margin`: optional, in PDF points (default 0): pads each box outward so the outline sits around the
  image instead of on its edge, clamped to the page. A negative value is a 400.
- Render resolution is `DOC_ANNOTATE_DPI` (default 100).
- Same 400 `{"error": "..."}` cases as `/extract-images`.

## `POST /extract-markdown`

```bash
curl -X POST "http://localhost:8003/extract-markdown" \
  -F "file=@document.pdf;type=application/pdf" \
  -F "page=1" -o page1.md
```

Stitches one page's text, tables and images into a single Markdown file (`text/markdown`, named
`page-N.md`) in source reading order, placing each element by its bbox (top, then left). It reuses the
detection behind `/extract-text`, `/extract-tables` and `/extract-images`.

- Form fields: `file`, `page` (default 1; exactly one page), optional `x_tolerance_ratio` (as in
  `/extract-text`) and `image_dpi` (crop resolution, default `DOC_ANNOTATE_DPI`).
- The page is analyzed first (the same `has_text` / `has_table` / `has_image` flags `/analyze` reports)
  and the flags pick the approach: tables are rendered only when ruled tables are detected (no
  text-alignment fallback, so prose is never turned into a table), images only when the page has
  them, text only when it has a text layer.
- Text lines are kept as paragraphs (lines close together share a paragraph); tables are GFM tables;
  text inside a table or image bbox is not repeated.
- Images (touching fragments merged, as in `/annotate-images`) are cropped from the page render and
  embedded as `![<bbox[x0, top, x1, bottom]>image N](data:image/png;base64,...)`, the bbox being in PDF
  points, top-left origin.
- A page with neither a text layer nor images returns 204.
- Same 400 `{"error": "..."}` cases as `/extract-tables`, plus `image_dpi` below 1.

## `POST /extract-words`

```bash
curl -X POST "http://localhost:8003/extract-words" \
  -F "file=@document.pdf;type=application/pdf" \
  -F "page=1" -o page1.docx
```

One page -> one Word file (`.docx`, named `page-N.docx`) that keeps the PDF layout. It uses the same
detection and stitching as `/extract-markdown` (shared `_page_elements`), but instead of flowing the
content it pins every element to its bbox on a Word page of the PDF page's size (no margins).

- Form fields: `file`, `page` (default 1), optional `x_tolerance_ratio`, `image_dpi` and `all_pages`.
- `all_pages=true`: every page goes into the same Word file, one section per page (each with its own page
  size and header/footer), named `<upload name>.docx`; `page` is ignored. Pages with neither a text layer nor
  images are skipped, and the response is 204 only when every page is like that.

```bash
curl -X POST "http://localhost:8003/extract-words" \
  -F "file=@document.pdf;type=application/pdf" -F "all_pages=true" -o document.docx
```

- Text: each line, split where there is a wide gap (as `/extract-markdown` does with `DOC_GAP_SEPARATOR`),
  becomes a paragraph frame at the segment's bbox, with the font size, family and bold/italic taken from
  the PDF glyphs. Stays editable text.
- Header/footer: text lines wholly inside the top / bottom `DOC_MARGIN_RATIO` band (the same bands
  `/analyze` uses for `has_header` / `has_footer`) go into the Word header / footer instead of the body,
  pinned at the same page position. A printed page number stays literal text, not a PAGE field.
  The header/footer extent is reserved as the page's top/bottom margin (plus a 2pt gap), so body content
  added in Word can't overlap them; the pinned elements don't move.
- Tables: a real Word table, floated at the table bbox, with column widths and row heights from the
  detected cell edges and merged cells as spans. Words inside the table border but outside any cell
  become text frames.
  A table reaching into the header/footer band is squeezed to sit between them: only the edge in the
  band moves, the edge facing neighbouring content stays put (a small departure from its PDF bbox, so it
  can't overlap them). Rows have exact heights so Word can't
  grow the table past that.
- Images: cropped from the page render and anchored behind the text at their bbox.
- Elements are written in reading order (top, then left); text inside a table or image bbox is not
  repeated.
- 204 for a page with neither a text layer nor images; same 400 cases as `/extract-markdown`.
- Limits: fonts are mapped to common families, so Word's substitute font can differ slightly in width
  (frames have a little slack so lines never wrap); rotated pages and non-zero CropBox origins are
  placed in pdfplumber's page frame; no OCR.

## `POST /image-to-words`

```bash
curl -X POST "http://localhost:8003/image-to-words" \
  -F "file=@menu.png;type=image/png" -o menu.docx
```

One image -> one Word file (`<upload name>.docx`). The image is sent to `ocr-service`'s `/analyze`
(`DOC_OCR_URL`, default `http://127.0.0.1:8004`; `DOC_OCR_TIMEOUT`, default 300s), and each returned
`{text, bbox}` line becomes a paragraph frame pinned at its bbox on a Word page the size of the image
(96 dpi, no margins; scaled down if a side would exceed Word's 22 in limit). Font size is derived from the
box height (Arial); the text stays editable.

- Font size is fitted, not just taken from the box height: a tall box holding a wrapped paragraph gets
  the largest size (min 6 pt) at which the estimated wrapped text fits the box. A frame's width is capped
  at the start of the next box on the same row, so left text never runs into right text (e.g. a price);
  frames that still collide vertically are pushed down. `**bold**` markdown becomes bold runs.

- Ruled tables (a menu, a form) become real Word tables. The ruling lines are found with OpenCV, each
  enclosed area is a cell (so irregular grids and merged cells come out as gridSpan/vMerge), and the
  table is floated at its place on the page. The VLM's boxes on a whole dense page are too rough to
  tell cells apart and it skips lines, so each table row that shows ink is cropped (only its own cells,
  on white, 2x) and sent to `ocr-service` again; its lines pair left to right with the row's inked
  cells. When a row's read doesn't give one line per inked cell, those cells are read one by one
  (up to `DOC_OCR_TABLE_CELLS_MAX` per image, default 40); a cell whose own read fails keeps the row
  read's best guess (the line under it, split across cells on whitespace). Pieces of one visual line
  in a cell are joined into one line. Up to `DOC_OCR_TABLE_ROWS_MAX` rows (default 60) are read this
  way, about one extra small VLM call each; rows past it, or whose call fails, use the page call's
  lines. Page lines inside a table are not repeated as frames, nor are clamped page lines whose
  characters the table already holds.
- Boxes are model-estimated, so placement is approximate. The model often runs out of page at the
  bottom and collapses boxes (height under 2 px, e.g. `y1 == y2`) or squashes them against the image
  edge. Those lines are not dropped: they are rebuilt as rows below the last placed line in OCR order,
  keeping their own x (indents, right-hand prices); a price / tag or a line starting right of the
  previous label joins that label's row. The page grows to fit, so these rows sit past the image bottom.
- Errors are `{ "error": "<reason>" }`: 400 empty / not an image (also passed through from ocr-service),
  422 `no text detected in image`, 502 ocr-service unreachable or returned an error / invalid response,
  500 `could not build docx: ...`.

## POST /ground-state

Highlights where a *state* (a claim or fact) is grounded in a Word document.

```bash
curl -F file=@report.docx -F state="Revenue grew 12% in 2024" \
  http://localhost:8003/ground-state -o grounded.docx -i
```

- Splits the docx into lines (one per non-blank paragraph, body and table cells, in document order), sends
  `{state, context: lines}` to `translator-service` `POST /ground-state`, and receives
  `{groundings: [{line, start, end}]}` (char offsets inside that line, `end` exclusive).
- Highlights those spans (runs are split at the span edges, formatting kept) and returns the docx
  as `grounded-<name>.docx`.
- 404 `{"error": "state not found in document"}` when nothing could be grounded (including when the
  translator only returned out-of-range spans).
- 400 for an empty or non-docx upload, a blank `state`, or a docx with no text; 502 when
  `translator-service` is unreachable or answers with an error.
- Config: `DOC_TRANSLATOR_URL` (default `http://127.0.0.1:8001`), `DOC_GROUND_TIMEOUT` (seconds, default 120),
  `DOC_HIGHLIGHT_COLOR` (a Word highlight name, default `YELLOW`).
- Limits: headers/footers, footnotes and text boxes are not part of the context; a quote the LLM cannot
  match verbatim in a line is dropped.

## POST /giveme-suggestion

Highlights the parts of a Word document that fit a free-text *instruction* (e.g. "something light to eat"),
and summarizes them.

```bash
curl -F file=@menu.docx -F instruction="something light to eat" \
  http://localhost:8003/giveme-suggestion -i
```

- Same flow as `/ground-state`, but sends `{intent: instruction, context: lines}` to `translator-service`
  `POST /giveme-suggestion` and receives `{suggestions: [{line, start, end}]}`.
- The response is a **streamed `multipart/mixed`** body (`Content-Type: multipart/mixed; boundary=<hex>`) with
  two parts, in this order:
  1. the highlighted docx (`Content-Type` docx, `Content-Disposition: attachment; filename*=UTF-8''suggested-<name>.docx`),
     sent as soon as it is built;
  2. `application/json`: `{"summary": "...", "highlights": ["...", ...]}`. `highlights` are the highlighted
     texts in document order; `summary` comes from `translator-service` `POST /summarize-suggestion`
     (`{intent, highlights}`). If that call fails, the part is `{"error": "...", "highlights": [...]}`
     instead (the status is already 200 by then).

  ```text
  --3f2c...
  Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
  Content-Disposition: attachment; filename*=UTF-8''suggested-menu.docx

  <docx bytes>
  --3f2c...
  Content-Type: application/json

  {"summary": "Try the garden salad ...", "highlights": ["Garden salad with yuzu dressing"]}
  --3f2c...--
  ```
- Errors are decided before streaming starts, so they are still plain JSON: 404 `{"error": "no suggestion found
  in document"}` when the translator suggests nothing (or only out-of-range spans); 400 for an empty or
  non-docx upload, a blank `instruction`, or a docx with no text; 502 when `translator-service` is unreachable
  or answers with an error.
- Config is shared with `/ground-state` (`DOC_TRANSLATOR_URL`, `DOC_GROUND_TIMEOUT`, `DOC_HIGHLIGHT_COLOR`), plus
  `DOC_SUMMARY_TIMEOUT` (seconds, default 120) for the summary call.

## POST /giveme-suggestion-pdf

`/giveme-suggestion` straight on a PDF, with no docx conversion: the instruction is grounded against the PDF's
own text lines, and the **original PDF** comes back with `/Highlight` annotations (the page content itself is
untouched).

```bash
curl -F file=@menu.pdf -F instruction="something light to eat" \
  http://localhost:8003/giveme-suggestion-pdf -i
```

- Lines are the same visual lines `/extract-text` reports (one per line, `DOC_GAP_SEPARATOR` between widely
  separated segments), across all pages in order; a span covering part of a word highlights just those chars.
- Same streamed `multipart/mixed` response as `/giveme-suggestion`, except the first part is
  `application/pdf` (`filename*=UTF-8''suggested-<name>.pdf`).
- **422** `{"error": "pdf has no usable text layer"}` when the PDF has no text layer (scanned) or a rotated page.
  The app then falls back to `/extract-words` + `/giveme-suggestion`, which handles both.
- Other errors as `/giveme-suggestion`: 400 for an empty or invalid PDF or a blank `instruction`, 404 when
  nothing maps onto the document, 502 when `translator-service` fails.
- Config: as `/giveme-suggestion`, plus `DOC_PDF_HIGHLIGHT_COLOR` (hex RGB, default `ffff00`).

## POST /giveme-suggestion-image

`/giveme-suggestion` straight on an image: `ocr-service` `/analyze` reads its lines, the instruction is grounded
against them, and `ocr-service` `/highlight` draws the grounded phrases onto the **original image**.

```bash
curl -F file=@menu.jpg -F instruction="something light to eat" \
  http://localhost:8003/giveme-suggestion-image -i
```

- Each grounded span goes to `/highlight` as `{line_text, line_bbox, start, end}` of its OCR line; ocr-service
  locates it with the model, or estimates it from the line box.
- Same streamed `multipart/mixed` response as `/giveme-suggestion`, except the first part is `image/png`
  (`filename*=UTF-8''suggested-<name>.png`).
- **422** `{"error": "no text detected in image"}` when OCR finds no text. 400 for an empty or invalid image or a
  blank `instruction`, 404 when nothing maps onto the text, 502 when `ocr-service` or `translator-service` fails.
  The app falls back to `/image-to-words` + `/giveme-suggestion` on 422 and 5xx.
- Config: `DOC_OCR_URL`, `DOC_OCR_TIMEOUT` (used for both OCR calls), plus the `/giveme-suggestion` ones.

## Scope note

This service classifies pages (`/analyze`), extracts text (`/extract-text`), converts tables to
Markdown (`/extract-tables`), locates images (`/extract-images`) and draws them on a page JPEG
(`/annotate-images`), and stitches a page into Markdown (`/extract-markdown`) or a position-faithful Word
file (`/extract-words`). `/image-to-words` OCRs an image through `ocr-service` into a Word file.
`/ground-state` and the `/giveme-suggestion*` endpoints highlight document text (docx, PDF or image) using
`translator-service` (and `ocr-service` for images). It does not OCR scanned PDF pages or describe image
content.

## Dev workflow

Run this service in one terminal (`uv run uvicorn app.main:app --port 8003`) alongside the services the
endpoints you use depend on (`translator-service` on 8001, `ocr-service` on 8004), and the Angular app
(`npm start`) in another. `start-dev.sh` (`npm run start-dev`) launches Angular and all the Python services together. The
Angular SSR server proxies `/api/pdf/analyze`, `/api/document/extract-words`, `/api/document/image-to-words`,
`/api/document/giveme-suggestion`, `/api/document/giveme-suggestion-pdf` and `/api/document/giveme-suggestion-image` to `DOCUMENT_SERVICE_URL` (env var, defaults to `http://localhost:8003`).
