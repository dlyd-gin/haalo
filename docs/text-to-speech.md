# Text-to-Speech

See also: [architecture.md](./architecture.md) for the ports/adapters pattern this fits into and
the overall service topology.

TTS only runs on the native-speaker reply flow: once a typed English reply has been translated,
the translated (foreign-language) text is synthesized to audio and played back — the foreign
speaker hears the reply, they don't read it.

## Port contract (`infrastructure/speech/tts.port.ts`)

Unlike `SttPort`/`TranslatorPort` (which stream text events), `TtsPort` hands back a **playback
handle** — the store manages *when* to play/pause, the handle just exposes the primitives:

```ts
interface TtsHandle {
  play(): Promise<void>;
  pause(): void;
  readonly errors: Observable<Error>;
  readonly ended: Observable<void>;
  dispose(): void;
}

interface TtsPort {
  preload(text: string, language: Language): TtsHandle;
}
```

`preload()` is called as soon as a reply's translation finishes (`conversation-store.ts`'s
`sendReply()`), *before* the user has necessarily pressed play — the audio starts downloading
immediately so it's ready by the time playback is requested (or autoplay kicks in, see below).

## `RealTtsAdapter` (`infrastructure/speech/real-tts.adapter.ts`)

Deliberately thin — it does no manual audio buffering itself:

```ts
const audio = new Audio();
audio.preload = 'auto';
audio.src = `/api/tts?text=${encodeURIComponent(text)}&language=${encodeURIComponent(language.code)}`;
```

A native `<audio>` element pointed at a streaming `audio/wav` URL handles progressive download
and playback on its own — the browser starts playing as soon as it has enough buffered, without
the adapter needing to read/queue byte chunks itself. `errors`/`ended` are just the element's own
`error`/`ended` DOM events, remapped to observables via `fromEvent`. `dispose()` pauses, clears
`src`, and calls `.load()` to release the underlying resource.

## `DummyTtsAdapter`

`play()`/`pause()` are no-ops; `ended` fires once via `timer(300ms)` instead of a real event, on
a delay specifically so callers can never be synchronously called back before their own
`preload()` call has returned (a real `<audio>` element's `ended` is always async too — the dummy
preserves that timing contract). Swapped in via `app.config.ts`'s provider list.

## Playback ordering (`application/conversation-store.ts`)

Translation + TTS synthesis are not request-serialized server-side, so **a later-sent reply's
audio can finish preloading before an earlier one's**. Autoplay still has to honor send order, so
the store keeps an explicit FIFO:

```ts
#playbackQueue: string[] = [];   // turn ids, in send order
#isAutoPlaying = false;
```

```
sendReply(A) ──► playbackQueue: [A]
sendReply(B) ──► playbackQueue: [A, B]     (B's translation/TTS might resolve first!)

#tryPlayNextInQueue():
  ┌─────────────────────────────────────────────────────────┐
  │ already auto-playing? ──yes──► do nothing (next 'ended'  │
  │        │no                      /'error' will re-trigger)│
  │        ▼                                                  │
  │ peek playbackQueue[0]  (always A, never B, while A is    │
  │        │                head-of-queue — regardless of     │
  │        ▼                which finished preloading first)  │
  │ is A's TtsHandle preloaded yet?                            │
  │        │no ──► bail; A's own 'done' handler will call     │
  │        │        #tryPlayNextInQueue() again once ready     │
  │        │yes                                                │
  │        ▼                                                   │
  │ play A; on `ended` OR `errors` (whichever first) →         │
  │   pop A off the queue, #tryPlayNextInQueue() again (→ B)   │
  └─────────────────────────────────────────────────────────┘
```

So B's audio may finish *downloading* before A's, but it never plays before A — `#tryPlayNextInQueue`
always checks the head of the queue, not "whichever just became ready."

Manual playback (pressing play on a specific bubble via `playTurnAudio(turnId)`) bypasses the
queue entirely — it's direct, user-initiated, and doesn't touch `#playbackQueue`/`#isAutoPlaying`.
The queue only governs *automatic* playback triggered by a reply becoming ready.

## Backend: `tts-service`

FastAPI + [mlx-audio](https://github.com/Blaizzy/mlx-audio), Apple Silicon only. Single real
endpoint:

```
GET /synthesize?text=<...>&language=<code>   →   audio/wav (streamed chunks)
```

Model: `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`. `language` is mapped to a specific voice via
`LANGUAGE_VOICE_MAP` in `config.py` (a 400 is returned for an unmapped language). As with
`stt-service`, MLX generation is CPU/GPU-bound and blocking, so `main.py` runs synthesis in a
**worker thread**, bridging its blocking generator onto the event loop with `call_soon_threadsafe`
+ an `asyncio.Queue`, yielding raw WAV byte chunks as a `StreamingResponse`. An `anyio.Lock` is
held for the *entire* stream (not just per-call) because the shared model instance keeps mutable
streaming-decoder state on itself — concurrent requests would otherwise race and corrupt each
other's output. A mid-stream failure can't be reported as a JSON error (the response is already a
raw `audio/wav` body by then) — it just logs server-side and ends the stream early, which the
client sees as a truncated/failed download.

`src/server.ts` proxies `GET /api/tts` straight to `tts-service`'s `/synthesize`, piping the
response body through unbuffered (`TTS_SERVICE_URL`, default `http://localhost:8000`) — this is
exactly what lets `RealTtsAdapter`'s plain `<audio src="/api/tts?...">` work without the browser
ever needing to know a separate Python process is involved.
