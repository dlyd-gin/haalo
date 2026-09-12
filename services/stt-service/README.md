# stt-service

Minimal FastAPI wrapper around [mlx-audio](https://github.com/Blaizzy/mlx-audio) that serves a single
`/transcribe` endpoint for the travel-translator app's speech-to-text feature. Apple Silicon (MLX)
only — this service does not run on Linux/Intel or in typical CI.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and `ffmpeg` on `PATH` (used by mlx-audio's `audio_io` to
decode the WebM/Opus audio a browser `MediaRecorder` produces — WAV/FLAC/MP3 decode without it via
`miniaudio`, but WebM/Opus/M4A do not).

```bash
uv sync
```

Download the model manually (not fetched automatically at runtime):

```bash
uv run hf download mlx-community/Qwen3-ASR-1.7B-8bit \
  --local-dir models/Qwen3-ASR-1.7B-8bit
```

Copy `.env.example` to `.env` and adjust if needed (defaults already point at the path above).

## Run

From the repo root:

```bash
cd services/stt-service
uv run uvicorn app.main:app --host 127.0.0.1 --port 8002 --log-level debug --reload
```

Confirm it's up:

```bash
curl http://localhost:8002/health
```

## API

`POST /transcribe?language=...`

```bash
curl -X POST "http://localhost:8002/transcribe?language=ja" \
  --data-binary @clip.webm \
  -H "Content-Type: audio/webm"
```

Takes the raw audio bytes as the request body (no multipart) and returns a `text/event-stream` of
newline-delimited `data: {json}` frames as the transcript is decoded:

- `{"type": "delta", "text": "..."}` — a chunk of transcript text as it's produced
- `{"type": "done", "text": "...", "language": "..."}` — the full accumulated transcript
- `{"type": "error", "message": "..."}` — decoding failed mid-stream

`language` must be one of the keys in `app/config.py`'s `LANGUAGE_MAP` (currently `en`, `ja`, `zh`,
`ko`) or the request 400s.

## Known risk: Japanese language name mapping unvalidated

`LANGUAGE_MAP` translates the app's canonical language codes into the language names Qwen3-ASR's
`generate(language=...)` expects, matched case-insensitively against the model's
`config.support_languages` list. `zh` -> `chinese` is confirmed present in the downloaded model's
`support_languages` (see command below). `ja` -> `japanese` hasn't been validated against a real
Japanese clip yet — sanity-check it:

```bash
python -c "import json; print(json.load(open('models/Qwen3-ASR-1.7B-8bit/config.json')).get('support_languages'))"
```

and confirm a real Japanese clip transcribes correctly via the `/transcribe` curl example above. If
the language name doesn't match, adjust `LANGUAGE_MAP` in `app/config.py`.

## Scope note

This service does speech transcription only — no translation. The text returned by `/transcribe` is
in the same language it was spoken; producing an English rendering is the caller's responsibility (a
separate translation step, not implemented here — see `translator-service`).

## Dev workflow

Run this service in one terminal (`uv run uvicorn app.main:app --port 8002`) alongside `tts-service`
and `translator-service`, and the Angular app (`npm start`) in another. The Angular SSR server proxies
`/api/stt` to `STT_SERVICE_URL` (env var, defaults to `http://localhost:8002`).
