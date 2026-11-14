# translator-service

Minimal FastAPI wrapper around [mlx-lm](https://github.com/ml-explore/mlx-lm) that prompts a
chat-tuned LLM (`mlx-community/Qwen3-8B-4bit`) to translate text, serving a single `/translate`
endpoint for the travel-translator app. Apple Silicon (MLX) only — this service does not run on
Linux/Intel or in typical CI.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Download the model manually (not fetched automatically at runtime):

```bash
uv run hf download mlx-community/Qwen3-8B-4bit \
  --local-dir models/Qwen3-8B-4bit
```

Settings are environment variables prefixed `TRANSLATOR_` (see `app/config.py`); the defaults already
point at the path above. Override the model location with `TRANSLATOR_MODEL_PATH`.

## Run

From the repo root:

```bash
cd services/translator-service
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --log-level debug --reload
```

Confirm it's up:

```bash
curl http://localhost:8001/health
```

## API

`POST /translate`

```json
{ "text": "Where is the train station?", "source_language": "en", "target_language": "ja" }
```

Streams Server-Sent Events (`text/event-stream`), one JSON object per `data:` line:

```
data: {"type": "delta", "text": "駅は"}
data: {"type": "delta", "text": "どこですか？"}
data: {"type": "done", "answer": "駅はどこですか？", "rephrased_text": "Where is the train station?"}
```

A failure mid-stream is sent as `{"type": "error", "message": "..."}`.

Translation happens in two LLM calls. Step 1 rephrases the raw input for grammar/clarity
(`REPHRASE_SYSTEM_PROMPT` in `app/engine/translator_engine/rephrase_engine/system_prompt.py`); it runs
to completion and is returned as `rephrased_text` in the `done` event. Step 2 runs the translation
prompt (`build_system_prompt` in `app/engine/translator_engine/translate_engine/system_prompt.py`)
against that rephrased text and streams the `delta` chunks. Thinking is disabled for both calls, so
there is no reasoning trace in the output.

`source_language`/`target_language` must each be one of the keys in `app/config.py`'s
`SUPPORTED_LANGUAGES` (currently `en`, `jp`, `zh`, `ko`; note `jp`, not `ja`, for Japanese — the Angular
`RealTranslatorAdapter` maps the app's `ja` to it). Validation errors are plain JSON with status 400:
an empty `text`, or an unsupported language:

```json
{ "error": "unsupported target_language: fr" }
```

Try it both directions:

```bash
curl -N -X POST http://localhost:8001/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Where is the train station?","source_language":"en","target_language":"jp"}'

curl -N -X POST http://localhost:8001/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"すみません、駅はどこですか？","source_language":"jp","target_language":"en"}'
```

## Known risk: this is a general-purpose LLM, not a dedicated translation model

`Qwen3-8B-4bit` is prompted (via a system instruction + chat template) to act as a translator — it
isn't a model purpose-built and evaluated for translation. The `answer` isn't guaranteed to be
translation-only: it could add commentary, refuse, wrap the result in quotes, or otherwise deviate
from a clean translation. Validate by eye before relying on it, and adjust the prompt in
`app/engine/translator_engine/translate_engine/system_prompt.py` if the output needs tighter
constraining.

## Integration

The Angular app reaches `/translate` through the Node proxy `POST /api/translate` in `src/server.ts`
(upstream: `TRANSLATOR_SERVICE_URL`, default `http://localhost:8001`), consumed by
`RealTranslatorAdapter`. `document-service` calls `/giveme-suggestion`, `/ground-state` and
`/summarize-suggestion` directly.

## Dev workflow

Each Python service has its own port: tts 8000, translator 8001, stt 8002, document 8003, ocr 8004.
`start-dev.sh` (`npm run start-dev`) starts Angular plus all the services; to run this one alone:
`uv run uvicorn app.main:app --host 127.0.0.1 --port 8001`.

## POST /ground-state

Locates a *state* inside document lines using the same Qwen3 model (weights are shared with `/translate`).

```bash
curl -X POST http://localhost:8001/ground-state -H 'content-type: application/json' \
  -d '{"state": "Revenue grew 12%", "context": ["Intro", "In 2024 revenue grew 12% year over year."]}'
# {"groundings":[{"line":1,"start":8,"end":28}]}
```

- `context` is the document line by line; `line` indexes into it, `start`/`end` are char offsets within
  that line (`end` exclusive), ready for highlighting.
- The model only returns the supporting quote; offsets are computed in code (exact, then case- and
  whitespace-insensitive match), and quotes that cannot be found are dropped.
- `groundings` is `[]` when nothing supports the state (still 200; `document-service` turns that into a 404).
- 400 for a blank `state` or empty `context`; 503 while the model loads. Cap output with
  `TRANSLATOR_GROUND_MAX_TOKENS` (default 512).
- Debugging: `TRANSLATOR_LOG_LEVEL=DEBUG` (default `INFO`) logs the state, the prompt, the raw model output and the resolved spans.

## POST /giveme-suggestion

Like `/ground-state`, but an *intent* (no state) shapes what gets picked: the model returns the context spans that
best fit the intent (same shared model, same quote-to-offset resolution).

```bash
curl -X POST http://localhost:8001/giveme-suggestion -H 'content-type: application/json' \
  -d '{"intent": "eat something light", "include_reason": true,
       "context": ["Menu", "Tonkotsu ramen with pork belly", "Garden salad with yuzu dressing"]}'
# {"suggestions":[{"line":2,"start":0,"end":12,"reason":"Low-calorie vegetable dish"}]}
```

- Each quote covers the whole suggested item (e.g. a menu entry's name plus its description), not just the matching keyword.
- An intent may name several things ("turkish bread with bacon"): each is matched on its own, `+ ADD-ON` lines count as items, and a dish that mentions the ingredient fits.
- An add-on (`+ ...` line) belongs to the dish directly above it: asking for a dish's add-ons returns only that dish's, not those of the next dish.
- `include_reason` (default `false`) adds a short `reason` per suggestion; when `false` the key is omitted.
- `suggestions` is `[]` when nothing fits (still 200). `line`/`start`/`end` have the same meaning as in `/ground-state`.
- 400 for a blank `intent` or empty `context`; 503 while the model loads. Cap output with
  `TRANSLATOR_GIVEME_MAX_TOKENS` (default 8192).
- Unlike `/translate`, this runs Qwen3 in thinking mode, which must not decode greedily, so it samples:
  `TRANSLATOR_GIVEME_TEMPERATURE` (0.4), `TRANSLATOR_GIVEME_TOP_P` (0.95), `TRANSLATOR_GIVEME_TOP_K` (20).
  `TRANSLATOR_GIVEME_INTENT_MAX_TOKENS` (64) caps the intent-rewrite pass.

## POST /summarize-suggestion

Turns the spans `/giveme-suggestion` picked into a short English answer to the intent (`document-service`
sends this after highlighting, as the summary part of its own `/giveme-suggestion` response).

```bash
curl -X POST http://localhost:8001/summarize-suggestion -H 'content-type: application/json' \
  -d '{"intent": "eat something light", "highlights": ["Garden salad with yuzu dressing", "Miso soup"]}'
# {"summary":"Try the garden salad with yuzu dressing, or a bowl of miso soup."}
```

- 1-3 sentences, using only the highlighted items (same shared model, no thinking block).
- `+ ...` add-on highlights are grouped under the dish highlighted right before them (giveme-suggestion
  always highlights an add-on's dish too), so the summary names them together ("GREEN BOWL with poached egg")
  instead of the add-on alone.
- 400 for a blank `intent` or no non-blank `highlights`; 500 `summary failed: ...` on an engine error;
  503 while the model loads.
