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

Copy `.env.example` to `.env` and adjust if needed (defaults already point at the path above).

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

Returns JSON:

```json
{ "thinking": "...", "answer": "駅はどこですか？", "rephrased_text": "Where is the train station?" }
```

Translation happens in two LLM calls. Step 1 rephrases the raw input for grammar/clarity
(`REPHRASE_SYSTEM_PROMPT`); its result is returned as `rephrased_text`. Step 2 runs the existing
translation prompt (`SYSTEM_PROMPT`) against that rephrased text. Qwen3 is a reasoning model — the
step 2 call replies with a `<think>...</think>` block before its actual answer.
`app/translator_engine.py` splits that block out: `thinking` holds the model's reasoning trace for
the translation step (empty string if the model didn't emit one), `answer` holds the actual
translation.

`source_language`/`target_language` must each be one of the keys in `app/config.py`'s
`SUPPORTED_LANGUAGES` (currently `en`, `jp`, `zh`, `ko`) or the request 400s with `{ "error": "..." }`,
e.g.:

```json
{ "error": "unsupported target_language: fr" }
```

Try it both directions:

```bash
curl -X POST http://localhost:8001/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Where is the train station?","source_language":"en","target_language":"ja"}'

curl -X POST http://localhost:8001/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"すみません、駅はどこですか？","source_language":"ja","target_language":"en"}'
```

`zh` (Mandarin) was validated live against the running service in both directions —
`en`->`zh` returned `火车站位于哪里？` for "Where is the train station?", and `zh`->`en` returned
"Where is the station?" for `请问车站在哪里？`.

## Known risk: this is a general-purpose LLM, not a dedicated translation model

`Qwen3-8B-4bit` is prompted (via a system instruction + chat template) to act as a translator — it
isn't a model purpose-built and evaluated for translation. Beyond the `<think>` block already split
out into `thinking`, the `answer` field still isn't guaranteed to be translation-only: it could add
commentary, refuse, wrap the result in quotes, or otherwise deviate from a clean translation.
Validate by eye before relying on it, and adjust `SYSTEM_PROMPT` in `app/translator_engine.py` if
the model's output needs tighter constraining.

## Scope note

This service is standalone for now — it is not yet wired into the Angular app (no Node proxy
route, no frontend adapter). `RealTtsAdapter` still speaks reply text as-is in the target voice
without translating it first. Wiring this service into that flow is a separate, later change.

## Dev workflow

Run this service in its own terminal (`uv run uvicorn app.main:app --host 127.0.0.1 --port 8001`),
alongside `tts-service` (`--port 8000`) and the Angular app (`npm start`) in their own terminals.
Ports are distinct (8000 vs 8001) so both Python services can run at once.
