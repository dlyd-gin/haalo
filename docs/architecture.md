# Frontend Architecture

See also: [ux.md](./ux.md) for the UX/design rationale behind these panels and layouts,
[speech-to-text.md](./speech-to-text.md) and [text-to-speech.md](./text-to-speech.md) for the
voice pipelines this architecture supports.

## System overview

```
┌───────────────────────────────────────────────────────────────────┐
│ Browser (Angular 21, zoneless, SSR-hydrated)                      │
│  presentation/ → application/ → domain/ (pure) + infrastructure/  │
└───────────────────────────┬─────────────────────────────────────┘
                              │ fetch: /api/stt, /api/tts, /api/translate
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│ src/server.ts — Angular SSR Node/Express server (port 4000)       │
│  also proxies each /api/* route straight through to one service  │
└───┬───────────────────┬───────────────────┬─────────────────────┘
     │ /api/stt          │ /api/tts           │ /api/translate
     ▼                    ▼                     ▼
┌───────────┐      ┌────────────┐        ┌───────────────────┐
│ stt-service│      │ tts-service│        │ translator-service │
│ :8002      │      │ :8000      │        │ :8001               │
│ FastAPI +  │      │ FastAPI +  │        │ FastAPI + MLX        │
│ mlx-audio  │      │ mlx-audio  │        │ Qwen3-8B-4bit         │
│ Qwen3-ASR  │      │ Qwen3-TTS  │        │                       │
└───────────┘      └────────────┘        └───────────────────┘
```

All three Python services are Apple Silicon/MLX-only, run as separate local processes, and are
each a thin FastAPI wrapper with exactly one real endpoint (`/transcribe`, `/synthesize`,
`/translate`) plus `/health`. `src/server.ts` proxies `/api/stt` → `stt-service`, `/api/tts` →
`tts-service`, `/api/translate` → `translator-service` (URLs configurable via
`STT_SERVICE_URL`/`TTS_SERVICE_URL`/`TRANSLATOR_SERVICE_URL` env vars), streaming each upstream
response body straight through rather than buffering it. The Angular app never talks to the
Python services directly — it only ever calls same-origin `/api/*`.

## DDD-lite layering

Framework-agnostic domain logic is kept separate from Angular so business rules stay unit-testable
without a `TestBed`, and infrastructure (real STT/TTS/translation) sits behind swappable ports.

```
┌─────────────────────────────────────────────────────────────────────┐
│ presentation/                                    (Angular)          │
│  ┌───────────────┐   ┌───────────────┐                              │
│  │ foreign-speaker│   │ native-speaker│   features — thin, delegate │
│  │  (component)   │   │  (component)  │   all logic to the store    │
│  └───────┬───────┘   └───────┬───────┘                              │
│          │      reads signals / calls methods    │                  │
│          └───────────────┬───────────────────────┘                  │
└──────────────────────────┼───────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│ application/conversation-store.ts                  (Angular DI)     │
│   signal() state (turns, isRecording, playingTurnId, …)             │
│   orchestrates side effects, calls pure domain rules to transform   │
│   state, drives ports                                                │
└───────┬───────────────────────────────────────────────────┬─────────┘
         │ calls pure functions                              │ calls via
         ▼                                                    │ InjectionToken
┌───────────────────────────────────┐          ┌──────────────▼────────────────┐
│ domain/                            │          │ infrastructure/                │
│  (no Angular imports — pure)       │          │  STT_PORT, TTS_PORT,            │
│  conversation-turn.rules.ts:        │          │  TRANSLATOR_PORT — each an      │
│   addRecordingTurn(turns, turn)     │          │  InjectionToken + interface,    │
│   markTurnStreaming(turns, id)      │          │  with a dummy/* + real/*        │
│   appendTranslationDelta(...)       │          │  adapter behind it.             │
│   → new turns[] out, no mutation    │          │  Details: speech-to-text.md /   │
│                                      │          │  text-to-speech.md              │
│  language/ (Language type,          │          │                                  │
│   SUPPORTED_LANGUAGES catalog)      │          │                                  │
└───────────────────────────────────┘          └──────────────────────────────┘
```

Swapping `Real*Adapter` for `Dummy*Adapter` (e.g. for a demo without the Python services running)
is a one-line change in `app.config.ts`'s provider list — no component or store changes needed.

## Folder structure

```
src/
├── server.ts                         Express SSR server + /api/* proxy to the 3 services
└── app/
    ├── app.ts / app.html / app.scss     root shell — renders header + both panels,
    │                                      reads LayoutPreferencesStore for orientation
    ├── app.config.ts                     DI wiring: real adapters bound to each port,
    │                                      SSR hydration, HTTP client
    │
    ├── domain/                           framework-agnostic, pure — no Angular imports
    │   ├── conversation/
    │   │   ├── conversation-turn.ts        ConversationTurn type, SplitId, TurnStatus
    │   │   └── conversation-turn.rules.ts  pure reducer functions (+ .spec.ts tests)
    │   └── language/
    │       ├── language.ts                 Language type
    │       ├── language-catalog.ts         SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
    │       └── language.rules.ts           pure helpers (+ .spec.ts tests)
    │
    ├── application/
    │   └── conversation-store.ts         the one @Injectable orchestrator — all app
    │                                       state as signals, drives ports, calls domain
    │                                       rules, owns TTS playback queue ordering
    │
    ├── infrastructure/                   adapters behind ports — swappable, DI-bound
    │   ├── http/http-error.util.ts
    │   ├── speech/                         see speech-to-text.md + text-to-speech.md
    │   │   ├── stt.port.ts / tts.port.ts
    │   │   ├── dummy-stt.adapter.ts / dummy-tts.adapter.ts
    │   │   ├── real-stt.adapter.ts / real-tts.adapter.ts
    │   │   └── wav-encoder.ts
    │   └── translation/
    │       ├── translator.port.ts
    │       └── real-translator.adapter.ts   talks to translator-service over HTTP
    │
    └── presentation/                     everything Angular-UI
        ├── features/
        │   ├── foreign-speaker/            voice-in panel — thin, delegates to store
        │   └── native-speaker/             typed-in panel — composer expand/collapse,
        │                                    focus management, mic dictation into draft
        ├── layout/
        │   └── layout-preferences.ts       orientation resolution + manual override
        ├── shared/                         reusable leaf components
        │   ├── app-header/
        │   ├── icon/
        │   ├── language-picker/
        │   ├── message-bubble/             renders a ConversationTurn by status
        │   ├── mic-button/                 press-and-hold recording control
        │   └── orientation-toggle/
        └── styles/
            ├── _tokens.scss                design tokens (color/space/type/motion/glass)
            └── _glass.scss                 liquid-glass mixins, read tokens only

services/                              separate Python backends (outside the Angular app)
├── stt-service/                       FastAPI + mlx-audio, Apple Silicon only
├── tts-service/                       FastAPI + mlx-audio, Apple Silicon only
└── translator-service/                FastAPI + Qwen3-8B-4bit, Apple Silicon only
```

## Notable technical patterns

- **Zoneless** — no `zone.js`. All async UI updates go through explicit `signal.set()` /
  `.update()`. Manual `effect()` for focus management, `afterNextRender` + `DestroyRef.onDestroy`
  for DOM/global listeners (`native-speaker.ts`, `layout-preferences.ts`) instead of relying on
  change detection noticing things on its own.
- **SSR-aware** — `provideClientHydration(withEventReplay())`; anything touching
  `window`/`document` is deferred into `afterNextRender` so it's skipped at prerender time.
- **Streaming ports** — `SttPort`/`TranslatorPort` return `Observable<...Event>` with
  `delta`/`done`/`error` variants, so the store appends partial text turn-by-turn. See
  [speech-to-text.md](./speech-to-text.md) for the STT/translation-chaining specifics and
  [text-to-speech.md](./text-to-speech.md) for how `TtsPort` differs (it hands back a playback
  handle rather than a stream of text events).
