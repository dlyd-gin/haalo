# Speech-to-Text

See also: [architecture.md](./architecture.md) for the ports/adapters pattern this fits into and
the overall service topology.

STT is used on both panels, but for different purposes:

- **`foreign-speaker`** — the full voice-to-translated-text flow: capture → transcribe → *chained
  translation* → a `ConversationTurn` streams through `recording → processing → streaming →
  ready`.
- **`native-speaker`** — dictation only: capture → transcribe → the raw transcript lands in the
  composer's `draftText` signal (`native-speaker.ts`), no `ConversationTurn` involved, no
  translation. The user can edit the dictated text before sending it as a normal typed reply.

## Port contract (`infrastructure/speech/stt.port.ts`)

```ts
type SttStreamEvent =
  | { type: 'source-delta'; text: string }        // partial transcript
  | { type: 'source-done'; sourceText: string }    // transcript finalized
  | { type: 'translation-delta'; text: string }    // partial translation (foreign-speaker only)
  | { type: 'done'; sourceText: string; translatedText: string } // fully finished
  | { type: 'error'; message: string };

interface SttPort {
  startCapture(): void;
  stopCapture(originSplit: SplitId, language: Language): Observable<SttStreamEvent>;
}
```

For a native-speaker capture, the observable completes right after `source-done` — there's no
`translation-delta`/`done` step, since dictation doesn't need translating.

## Streaming shape

```
foreign-speaker capture:
  startCapture() ── mic held ──► stopCapture()
                                     │
                          source-delta*  (live transcript chars)
                                     │
                          source-done   (transcript finalized)
                                     │
                    ┌────────────────┴────────────────┐
                    │  chained into translator-service │
                    └────────────────┬────────────────┘
                          translation-delta*  (live translation chars)
                                     │
                                   done         (sourceText + translatedText)

native-speaker capture (dictation):
  startCapture() ── mic held ──► stopCapture()
                                     │
                          source-delta*
                                     │
                          source-done   ──► observable completes (no translation step)
```

## `RealSttAdapter` (`infrastructure/speech/real-stt.adapter.ts`)

1. `startCapture()` calls `navigator.mediaDevices.getUserMedia({ audio: true })` and starts a
   `MediaRecorder` on the resulting stream, buffering `ondataavailable` chunks.
2. `stopCapture()` stops the recorder/stream, then **re-encodes the recording to 16-bit PCM WAV**
   before uploading:
   - Browsers' `MediaRecorder` produces WebM/Opus (Chrome) or M4A/AAC (Safari).
   - `stt-service` only decodes WAV/MP3/FLAC/Vorbis *without* a system `ffmpeg` binary on `PATH`
     (see its README's Scope note) — rather than requiring every dev machine to have `ffmpeg`
     installed, the adapter decodes the recording with the browser's own `AudioContext`, downmixes
     to mono, and hand-encodes a WAV container itself via `encodeMonoWav()`
     (`infrastructure/speech/wav-encoder.ts` — a pure function: `Float32Array` samples + sample
     rate in, a WAV `Blob` out, no DOM types, so it's unit-testable in isolation).
3. `POST /api/stt?language=<code>` with the WAV blob as the body (`Content-Type: audio/wav`).
4. The response is a `text/event-stream` (SSE) body; the adapter reads it frame-by-frame
   (`data: {...}\n\n`), parsing each JSON payload as `{ type: 'delta' | 'done' | 'error', ... }`
   and re-emitting it as the corresponding `SttStreamEvent`.
5. On the *foreign-speaker* path only, once `source-done` arrives, `translateAndComplete()` opens
   a second stream — this time against `TRANSLATOR_PORT` (translator-service, chained through the
   *same* `Observable<SttStreamEvent>` the store is subscribed to) — re-emitting its `delta`/`done`
   events as `translation-delta`/`done`. This is why `stt.port.ts`'s event union includes
   translation-shaped variants even though `stt-service` itself only ever transcribes: chaining
   happens client-side in the adapter, not server-side.
6. Aborting (component teardown, cancel) is wired through an `AbortController` shared across both
   the fetch and the chained translation subscription.

## `DummySttAdapter`

A `setTimeout`-scheduled fake timeline (`STEP_DELAY_MS = 300`) that emits the same event sequence
shape with placeholder text (`"[<Language> speech placeholder]"`), so the UI/store logic can be
exercised without a microphone, network, or the Python services running. Swapped in via
`app.config.ts`'s provider list.

## Backend: `stt-service`

FastAPI + [mlx-audio](https://github.com/Blaizzy/mlx-audio), Apple Silicon only. Single real
endpoint:

```
POST /transcribe?language=<code>      body: audio/wav      → text/event-stream
  data: {"type": "delta", "text": "..."}         (repeated, partial transcript)
  data: {"type": "done", "text": "...", "language": "..."}
  data: {"type": "error", "message": "..."}
```

Model: `mlx-community/Qwen3-ASR-1.7B-8bit` (downloaded manually into `models/`, not fetched at
runtime — see `services/stt-service/README.md`). Because `mlx-audio` decoding/inference is
CPU/GPU-bound and blocking, `main.py` runs the actual transcription in a **worker thread** and
bridges its blocking generator onto the async event loop via `call_soon_threadsafe` + an
`asyncio.Queue`, so the FastAPI event loop stays responsive while a transcription is in flight. An
`anyio.Lock` serializes concurrent requests against the one shared model instance, since it keeps
mutable streaming-decoder state on itself between calls.

`src/server.ts` proxies `POST /api/stt` straight to `stt-service`'s `/transcribe`, piping the
response body through unbuffered (`STT_SERVICE_URL`, default `http://localhost:8002`).
