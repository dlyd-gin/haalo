# stt-service

Minimal FastAPI wrapper around [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
(default, `whisper-large-v3-turbo`) and [mlx-audio](https://github.com/Blaizzy/mlx-audio) (Qwen3-ASR) that
serves a single `/transcribe` endpoint for the travel-translator app's speech-to-text feature. Apple Silicon (MLX)
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
uv run hf download mlx-community/whisper-large-v3-turbo \
  --local-dir models/whisper-large-v3-turbo
```

The default is `./models/whisper-large-v3-turbo`; override it with `STT_MODEL_PATH`. The engine picks
its backend from that path: any path containing `whisper-large-v3-turbo` (including a `-4bit` variant)
runs through mlx-whisper, anything else is loaded as a Qwen3-ASR model through mlx-audio, e.g.:

```bash
uv run hf download mlx-community/Qwen3-ASR-1.7B-8bit \
  --local-dir models/Qwen3-ASR-1.7B-8bit
STT_MODEL_PATH=./models/Qwen3-ASR-1.7B-8bit uv run uvicorn app.main:app --port 8002
```

Settings are environment variables prefixed `STT_` (`STT_MODEL_PATH`, `STT_HOST`, `STT_PORT`; see
`app/config.py`).

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
newline-delimited `data: {json}` frames as the transcript is decoded (with Whisper, decoding finishes
before the first frame, so `delta`s arrive one segment at a time rather than token by token):

- `{"type": "delta", "text": "..."}` — a chunk of transcript text as it's produced
- `{"type": "done", "text": "...", "language": "..."}` — the full accumulated transcript
- `{"type": "error", "message": "..."}` — decoding failed mid-stream

`language` is required and must be one of the keys in `app/config.py`'s `LANGUAGE_MAP` (currently `en`,
`ja`, `zh`, `ko`) or the request 400s; an empty body also 400s. Requests are serialized (one transcription
at a time).

## Known risk: language name mapping (Qwen3-ASR path)

`LANGUAGE_MAP` translates the app's canonical language codes into lowercase language names (`ja` ->
`japanese`, ...). Whisper accepts these names. For Qwen3-ASR they are matched case-insensitively against
the model's `config.support_languages` list, and `ja` -> `japanese` hasn't been validated against a real
Japanese clip there. If you switch to Qwen3-ASR, check the list:

```bash
python -c "import json; print(json.load(open('models/Qwen3-ASR-1.7B-8bit/config.json')).get('support_languages'))"
```

and confirm a real clip transcribes via the `/transcribe` curl example above. If a name doesn't match,
adjust `LANGUAGE_MAP` in `app/config.py`.

## Scope note

This service does speech transcription only — no translation. The text returned by `/transcribe` is
in the same language it was spoken; producing an English rendering is the caller's responsibility (a
separate translation step, not implemented here — see `translator-service`).

## Dev workflow

Run this service in one terminal (`uv run uvicorn app.main:app --port 8002`) alongside `tts-service`
(and `translator-service` if you want translation), and the Angular app (`npm start`) in another;
`start-dev.sh` launches Angular and all the Python services together. The Angular SSR server proxies
`/api/stt` to `STT_SERVICE_URL` (env var, defaults to `http://localhost:8002`).
