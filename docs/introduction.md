# Weekend project - Haalo

Every trip abroad runs into the same wall: you know enough of the language to order coffee, none of it to understand the answer. Translation apps solve this by phoning a cloud API — which means it stops working the moment your data plan does, and every sentence you speak leaves the device. That gap is what sent me down a rabbit hole of open-weight models for multiple weekend, chasing four questions:

1. Can an open-source model translate English into a foreign language well enough to actually use?
2. Can it play that translation back out loud, in a voice a stranger could understand?
3. Can it run in reverse — listen to a foreign speaker and turn their voice into your own language?
4. Can all of it happen *on the device in your pocket*, with nothing sent anywhere?

## What it feels like

Haalo is built for a conversation across a table, not a conversation with your phone. You type or speak in English on your side; the other person reads or hears the reply on theirs. An orientation toggle rotates the top panel 180° so it faces the other person right-side up instead of upside down — the phone becomes a small shared surface between two people instead of something passed back and forth screen-first. A flag by each panel marks which language is live, and the whole thing works in light or dark depending on where you're sitting.

The interaction layer was built weeks before any model was: every adapter that talks to a translator, a microphone, or a speaker sits behind a port, with a scripted "dummy" version standing in until the real one existed. It's a small architectural bet — keep the conversation UI honest and testable while the actual AI underneath is still being assembled piece by piece.

## The engine room

Underneath, Haalo is three small FastAPI services, each a thin wrapper around one open-weight model running through **MLX** — Apple's ML framework for its own chips. Nothing here calls out to the internet after the models are downloaded once.

| Step | Model | Service |
|---|---|---|
| Listen | Qwen3-ASR-1.7B | `stt-service` · :8002 |
| Translate | Qwen3-8B-4bit | `translator-service` · :8001 |
| Speak | Qwen3-TTS-1.7B | `tts-service` · :8000 |

Each endpoint streams — transcript deltas, then a translation, then WAV bytes — so the Angular front end never waits on a whole file before showing something.

The translation step is the interesting cheat: `Qwen3-8B-4bit` isn't a dedicated translation model, it's a general chat model prompted twice — once to quietly clean up the input's grammar, once to translate the cleaned version — with its reasoning trace stripped out of the final answer before it ever reaches the screen.

## Field notes — what's still rough

- Mandarin is validated end to end, both directions. Japanese speech-to-text and text-to-speech are wired up but not yet confirmed by ear against a real clip.
- A general-purpose chat model makes a scrappy translator — it's usually clean, but nothing stops it from adding a stray comment or wrapping an answer in quotes.
- The translator service runs and answers curl requests correctly, but isn't wired into the live app yet — today the reply is spoken as-is, translation still one plumbing pass away from the UI.

## Where you can help

This is still a weekend project, not a finished product, and there's real room to make it better:

- **UI/UX** — the table-flip layout and conversation flow work, but there's plenty of room to polish the interaction details, accessibility, and general feel.
- **Better STT/TTS model choices** — `Qwen3-ASR-1.7B` and `Qwen3-TTS-1.7B` were the first models that ran cleanly on MLX, not necessarily the best fit. If you know of models with a better size/quality trade-off, or ones that cover local dialects and accents these don't, that's a very welcome pointer.
- **Anything else** — bug reports, missing language pairs, rough edges in the setup docs, all fair game.
