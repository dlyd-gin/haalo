# tts-service

Minimal FastAPI wrapper around [mlx-audio](https://github.com/Blaizzy/mlx-audio) that serves a single
`/synthesize` endpoint for the travel-translator app's TTS feature. Apple Silicon (MLX) only — this
service does not run on Linux/Intel or in typical CI.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

Download the model manually (not fetched automatically at runtime):

```bash
uv run hf download mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit \
  --local-dir models/Qwen3-TTS-12Hz-1.7B-Base-8bit
```

Copy `.env.example` to `.env` and adjust if needed (defaults already point at the path above).

## Run

From the repo root:

```bash
cd services/tts-service
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level debug --reload
```

Confirm it's up:

```bash
curl http://localhost:8000/health
```

## API

`GET /synthesize?text=...&language=...`

```bash
curl -G http://localhost:8000/synthesize \
  --data-urlencode "text=Hello, where is the train station?" \
  --data-urlencode "language=en" \
  --output out.wav
```

GET (not POST) so an `<audio src>` element can point straight at this endpoint and stream
progressively. Returns `audio/wav` bytes as they're generated, with a streaming-WAV header
(RIFF/data chunk sizes left unspecified since the total length isn't known up front) — no
`Content-Length`, no HTTP Range/seeking support. `language` must be one of the keys in
`app/config.py`'s `LANGUAGE_VOICE_MAP` (currently `en`, `ja`, `zh`) or the request 400s.

## Known risk: `voice` names don't currently select a voice

The downloaded `Qwen3-TTS-12Hz-1.7B-Base-8bit` checkpoint's `config.json` has an **empty**
`talker_config.spk_id` table. mlx-audio only applies a named speaker embedding when the `voice`
string matches a `spk_id` key (`qwen3_tts.py`'s `_prepare_generation_inputs`); with no keys
present, every `voice` value in `LANGUAGE_VOICE_MAP` (`ryan`, `dylan`, ...) is currently a no-op —
they all produce the same single default voice. This is a property of the specific checkpoint,
not something this app's config controls; a checkpoint with populated `spk_id` (or voice cloning
via `ref_audio`/`ref_text`) would be needed for actual voice selection.

What *is* real is `language`: it maps to `config.talker_config.codec_language_id`, which the
downloaded checkpoint lists as `chinese`, `english`, `german`, `italian`, `portuguese`, `spanish`,
`japanese`, `korean`, `french`, `russian` — so output *language* is genuinely selected even though
voice *identity* isn't. `ja`'s output language quality is unvalidated; confirm by ear:

```bash
curl -G http://localhost:8000/synthesize \
  --data-urlencode "text=すみません、駅はどこですか？" \
  --data-urlencode "language=ja" \
  --output test-ja.wav
afplay test-ja.wav
```

If the output isn't intelligible Japanese, look at mlx-community's Qwen3-TTS `VoiceDesign` or
`CustomVoice` model variants, which may handle this differently.

## Mandarin voice

Mandarin (`zh`) was added and validated end-to-end against the running service — `codec_language_id`
includes `chinese`, and a live `/synthesize?language=zh` call returns a well-formed WAV (confirmed
via `file`; not confirmed by ear). Since Chinese is one of the checkpoint's core training languages
(unlike the Japanese stretch above), it's expected to be at least as reliable. The `dylan` voice name
is carried along for consistency with the `en`/`ja` entries, but per the risk note above it currently
selects nothing:

```bash
curl -G http://localhost:8000/synthesize \
  --data-urlencode "text=你好，请问车站在哪里？" \
  --data-urlencode "language=zh" \
  --output test-zh.wav
afplay test-zh.wav
```

## Scope note

This service does speech synthesis only — no translation. The text sent to `/synthesize` is spoken
as-is; producing text that's actually in the target language is the caller's responsibility (a
separate translation step, not implemented here).

## Dev workflow

Run this service in one terminal (`uv run uvicorn app.main:app --port 8000`) and the Angular app
(`npm start`) in another. The Angular SSR server proxies `/api/tts` to `TTS_SERVICE_URL` (env var,
defaults to `http://localhost:8000`).
