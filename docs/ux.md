# UX Design

A live conversation-translator app: one person speaks a foreign language (voice), the other
types English — each side sees the other's translated text/audio in real time on a shared
split screen.

See also: [architecture.md](./architecture.md) for the frontend layering and folder structure,
[speech-to-text.md](./speech-to-text.md) and [text-to-speech.md](./text-to-speech.md) for how
voice capture/playback actually work.

Designed for a phone/tablet lying flat on a table between two people, not held by one person.

## Two panels, two speaker roles

- `foreign-speaker` — voice input (press-and-hold mic → STT → translation → your language),
  rendered in the light-scoped theme.
- `native-speaker` — typed input (English → translation → TTS played back to the other person),
  rendered in the dark shell theme.

## Orientation — horizontal by default, vertical below 700px or on manual toggle

```
Horizontal (side-by-side, ≥700px or default)
┌──────────────────────────────────────────────┐
│                  app-header                  │
├──────────────────────┬───────────────────────┤
│                      │                       │
│   foreign-speaker    │    native-speaker      │
│   (light theme)      │    (dark theme)        │
│   voice in → STT     │    typed in → TTS out  │
│   → translated text  │    → translated text   │
│                      │                       │
└──────────────────────┴───────────────────────┘

Vertical (stacked, <700px or manual toggle — "device on table" mode)
┌──────────────────────────────────────────────┐
│                  app-header                  │
├──────────────────────────────────────────────┤
│         foreign-speaker (rotated 180°)        │  <- person across the table
│      ⇧ content flipped so it reads upright   │     reads this right-side up
│         from the other side of the table      │     without turning the device
├──────────────────────────────────────────────┤
│              native-speaker                   │  <- device owner reads this
│           (normal orientation)                │     normally
└──────────────────────────────────────────────┘
```

The vertical layout is the actual design driver: two people sitting across a table can both
read live output at once with zero tab-switching, and the foreign speaker never has to look at
upside-down text.

`LayoutPreferencesStore` (`presentation/layout/layout-preferences.ts`) resolves orientation from
`window.innerWidth` unless the user has explicitly clicked the toggle. The manual override starts
as `null` ("defer to the plain CSS `@media` breakpoint"), so first paint is correct with zero JS —
no hydration flash on SSR.

## Dual theme, tied by one shared accent

```
┌─ dark scope (:root) ──────────┐   ┌─ light scope ([data-panel='foreign']) ─┐
│ --color-bg:      #101114      │   │ --color-bg:      #faf9f6                │
│ --color-surface: #1c1e23      │   │ --color-surface: #ffffff                │
│ --color-text:    #edeef0      │   │ --color-text:    #17181b                │
│                                │   │                                          │
│ --color-accent:  #e8a33d  ────┼───┼─→ inherited unchanged (ties both halves  │
│                                │   │    together visually)                    │
└────────────────────────────────┘   └──────────────────────────────────────────┘
```

Amber/gold accent is reserved for points of action (mic ring, recording glow, focus rings, CTAs)
— never washed across an ambient background. Full token inventory lives in
`presentation/styles/_tokens.scss`.

## Turn-based streaming conversation log

Each utterance becomes a `ConversationTurn` that visibly moves through states as STT/translation/
TTS stream in, rendered as a `message-bubble`:

```
 recording → processing → streaming → ready
                 │                        │
                 └──────────→ error ←─────┘
```

- `recording` — mic held down, capturing audio (foreign-speaker only).
- `processing` — request in flight, nothing back yet.
- `streaming` — partial text arriving delta-by-delta (source transcript and/or translation).
- `ready` — final translated text set, TTS handle preloaded (if applicable).
- `error` — any stage failed; `errorMessage` set, shown via `.bubble__status--error`.

Partial STT/translation text appears live rather than popping in fully-formed once complete.
(The underlying streaming mechanics are covered in
[speech-to-text.md](./speech-to-text.md#streaming-shape) and
[text-to-speech.md](./text-to-speech.md).)

## Accessibility

`LiveAnnouncer` (Angular CDK, `@angular/cdk/a11y`) posts each turn's *final* translated text into
a hidden `aria-live="polite"` region so screen readers hear it without any visual/focus
disruption — fired once per turn, on completion, not per streaming delta (which would queue up
dozens of noisy fragments). Two call sites in `application/conversation-store.ts`:

- foreign-speaker STT `done` → announces the English translation
- native-speaker reply translation `done` → announces the foreign-language translation

The interim "still working" state is covered separately: `message-bubble.html`'s
`role="status" aria-label="Translating"` is an implicit `aria-live="polite"` region, so a screen
reader hears "Translating" once when that state appears.

Known gap: `error` turns are not currently announced to screen readers (visual-only via
`.bubble__status--error`) — a candidate follow-up.
