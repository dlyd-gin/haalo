import { Injectable, inject, signal } from '@angular/core';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { Observable, merge, take } from 'rxjs';
import {
  addRecordingTurn,
  addReplyTurn,
  appendSttSourceDelta,
  appendTranslationDelta,
  completeTtsTurn,
  createRecordingTurn,
  createReplyTurn,
  markSttSourceStreaming,
  markTurnError,
  markTurnProcessing,
  markTurnStreaming,
  resetConversation,
} from '../domain/conversation/conversation-turn.rules';
import { ConversationTurn } from '../domain/conversation/conversation-turn';
import { Language } from '../domain/language/language';
import { DEFAULT_LANGUAGE } from '../domain/language/language-catalog';
import { STT_PORT, SttStreamEvent } from '../infrastructure/speech/stt.port';
import { TTS_PORT, TtsHandle } from '../infrastructure/speech/tts.port';
import { TRANSLATOR_PORT } from '../infrastructure/translation/translator.port';

// The native-speaker panel (native-speaker) is always typed in English — there's no language
// picker for it, only the foreign side is selectable (see language-catalog.ts).
const NATIVE_LANGUAGE_CODE = 'en';

// Only .code is ever read downstream (the /api/stt query param) — the rest of this
// object satisfies SttPort's Language parameter, unused for the native mic flow.
const NATIVE_LANGUAGE: Language = {
  code: NATIVE_LANGUAGE_CODE,
  label: 'English',
  flag: '🇬🇧',
  flagCountryCode: 'gb',
};

@Injectable({ providedIn: 'root' })
export class ConversationStore {
  #stt = inject(STT_PORT);
  #tts = inject(TTS_PORT);
  #translator = inject(TRANSLATOR_PORT);
  #liveAnnouncer = inject(LiveAnnouncer);

  #turns = signal<ConversationTurn[]>([]);
  readonly turns = this.#turns.asReadonly();

  #foreignLanguage = signal<Language>(DEFAULT_LANGUAGE);
  readonly foreignLanguage = this.#foreignLanguage.asReadonly();

  #isRecording = signal(false);
  readonly isRecording = this.#isRecording.asReadonly();

  #isSending = signal(false);
  readonly isSending = this.#isSending.asReadonly();

  // Separate from #isRecording (foreign-speaker-specific) so each panel's mic-button can
  // disable itself while the other side holds the one shared MediaRecorder/MediaStream.
  #isNativeRecording = signal(false);
  readonly isNativeRecording = this.#isNativeRecording.asReadonly();

  #activeRecordingTurnId: string | null = null;
  #ttsHandles = new Map<string, TtsHandle>();

  // The turn whose audio is currently actually playing (not merely "ready") —
  // cleared on pause, on natural completion (`handle.ended`), and on error, so
  // the play button can reflect real playback state instead of a local guess.
  #playingTurnId = signal<string | null>(null);
  readonly playingTurnId = this.#playingTurnId.asReadonly();

  // Reply turn ids in send order — autoplay must honor this order even when a later
  // turn's translation/TTS stream resolves before an earlier one's (translation isn't
  // request-serialized server-side, so this can and does happen).
  #playbackQueue: string[] = [];
  #isAutoPlaying = false;

  setForeignLanguage(language: Language): void {
    console.log('[ConversationStore] foreign language changed', language.code);
    this.#foreignLanguage.set(language);
  }

  startRecording(): void {
    const id = crypto.randomUUID();
    const turn = createRecordingTurn(id, Date.now(), 'foreign-speaker', this.#foreignLanguage());
    this.#activeRecordingTurnId = id;
    this.#isRecording.set(true);
    this.#turns.update((turns) => addRecordingTurn(turns, turn));
    this.#stt.startCapture();
    console.log('[ConversationStore] startRecording', id);
  }

  stopRecording(): void {
    const id = this.#activeRecordingTurnId;
    if (!id) {
      return;
    }
    this.#activeRecordingTurnId = null;
    this.#isRecording.set(false);
    this.#turns.update((turns) => markTurnProcessing(turns, id));
    console.log('[ConversationStore] stopRecording, requesting STT', id);

    let hasSourceStreamStarted = false;

    this.#stt.stopCapture('foreign-speaker', this.#foreignLanguage()).subscribe({
      next: (event) => {
        switch (event.type) {
          case 'source-delta':
            if (!hasSourceStreamStarted) {
              hasSourceStreamStarted = true;
              this.#turns.update((turns) => markSttSourceStreaming(turns, id));
            }
            this.#turns.update((turns) => appendSttSourceDelta(turns, id, event.text));
            break;
          case 'source-done':
            this.#turns.update((turns) => markTurnStreaming(turns, id));
            break;
          case 'translation-delta':
            this.#turns.update((turns) => appendTranslationDelta(turns, id, event.text));
            break;
          case 'done':
            this.#turns.update((turns) => completeTtsTurn(turns, id));
            this.#liveAnnouncer.announce(event.translatedText, 'polite');
            break;
          case 'error':
            this.#turns.update((turns) => markTurnError(turns, id, event.message));
            break;
        }
      },
      error: (error: unknown) => {
        const message = error instanceof Error ? error.message : String(error);
        this.#turns.update((turns) => markTurnError(turns, id, message));
      },
    });
  }

  startNativeCapture(): void {
    this.#isNativeRecording.set(true);
    this.#stt.startCapture();
  }

  // Returns the raw stream rather than subscribing internally like stopRecording() does —
  // the transcript needs to land in NativeSpeaker's own draftText signal, not store-owned turn state.
  stopNativeCapture(): Observable<SttStreamEvent> {
    this.#isNativeRecording.set(false);
    return this.#stt.stopCapture('native-speaker', NATIVE_LANGUAGE);
  }

  sendReply(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    const id = crypto.randomUUID();
    const turn = createReplyTurn(id, Date.now(), trimmed, this.#foreignLanguage());
    this.#isSending.set(true);
    this.#turns.update((turns) => addReplyTurn(turns, turn));
    this.#playbackQueue.push(id);
    console.log('[ConversationStore] sendReply, requesting translation', id);

    const startedAt = performance.now();
    let firstDeltaAt = 0;
    let hasStreamStarted = false;

    this.#translator
      .translateStream(trimmed, NATIVE_LANGUAGE_CODE, this.#foreignLanguage().code)
      .subscribe({
        next: (event) => {
          if (event.type === 'delta') {
            if (!hasStreamStarted) {
              hasStreamStarted = true;
              firstDeltaAt = performance.now();
              console.log(
                `[ConversationStore] translate first delta in ${(firstDeltaAt - startedAt).toFixed(0)}ms`,
                id,
              );
              this.#turns.update((turns) => markTurnStreaming(turns, id));
            }
            this.#turns.update((turns) => appendTranslationDelta(turns, id, event.text));
            return;
          }

          const translatedAt = performance.now();
          console.log(
            `[ConversationStore] translate done in ${(translatedAt - startedAt).toFixed(0)}ms`,
            id,
            { rephrasedText: event.rephrasedText },
          );

          // Preload starts the audio stream immediately (eager, same trigger point as
          // before) — the turn is "ready" as soon as streaming has started, not once the
          // whole clip has finished generating/downloading.
          const handle = this.#tts.preload(event.translatedText, this.#foreignLanguage());
          this.#ttsHandles.set(id, handle);
          handle.errors.subscribe((error) => {
            this.#turns.update((turns) => markTurnError(turns, id, error.message));
            if (this.#playingTurnId() === id) {
              this.#playingTurnId.set(null);
            }
          });
          // Fires every time this clip finishes naturally (not `take(1)` — a
          // resumed/replayed clip can end more than once), so the play button
          // reverts on completion regardless of how playback was started.
          handle.ended.subscribe(() => {
            if (this.#playingTurnId() === id) {
              this.#playingTurnId.set(null);
            }
          });

          this.#turns.update((turns) => completeTtsTurn(turns, id));
          this.#liveAnnouncer.announce(event.translatedText, 'polite');
          this.#isSending.set(false);
          // Nudge the queue rather than playing `id` directly — an earlier-sent reply
          // might still be playing (or still preloading), and this turn has to wait its
          // turn even if it's the one that just became ready.
          this.#tryPlayNextInQueue();
        },
        error: (error: unknown) => {
          const message = error instanceof Error ? error.message : String(error);
          this.#turns.update((turns) => markTurnError(turns, id, message));
          this.#isSending.set(false);
          this.#removeFromPlaybackQueue(id);
          this.#tryPlayNextInQueue();
        },
      });
  }

  playTurnAudio(turnId: string): void {
    const handle = this.#ttsHandles.get(turnId);
    if (!handle) {
      return;
    }
    console.log('[ConversationStore] play requested', turnId);
    this.#playingTurnId.set(turnId);
    handle.play().catch((error: unknown) => {
      console.error('[ConversationStore] audio playback failed', error);
    });
  }

  pauseTurnAudio(turnId: string): void {
    const handle = this.#ttsHandles.get(turnId);
    if (!handle) {
      return;
    }
    console.log('[ConversationStore] pause requested', turnId);
    handle.pause();
    if (this.#playingTurnId() === turnId) {
      this.#playingTurnId.set(null);
    }
  }

  // Plays the head of `playbackQueue` once it's preloaded, in send order — a later
  // reply's audio can finish preloading first, but it still waits for its turn here.
  #tryPlayNextInQueue(): void {
    if (this.#isAutoPlaying) {
      return;
    }
    const nextId = this.#playbackQueue[0];
    if (!nextId) {
      return;
    }
    const handle = this.#ttsHandles.get(nextId);
    if (!handle) {
      return; // not preloaded yet — its own 'done' handler will nudge the queue again
    }

    this.#isAutoPlaying = true;
    let advanced = false;
    const advance = () => {
      if (advanced) {
        return;
      }
      advanced = true;
      this.#removeFromPlaybackQueue(nextId);
      this.#isAutoPlaying = false;
      this.#tryPlayNextInQueue();
    };

    // Either the clip finishing naturally or a playback error should release the queue —
    // whichever happens first.
    merge(handle.ended, handle.errors).pipe(take(1)).subscribe(advance);
    this.#playingTurnId.set(nextId);
    handle.play().catch((error: unknown) => {
      console.error('[ConversationStore] audio playback failed', error);
      advance();
    });
  }

  #removeFromPlaybackQueue(turnId: string): void {
    const index = this.#playbackQueue.indexOf(turnId);
    if (index !== -1) {
      this.#playbackQueue.splice(index, 1);
    }
  }

  reset(): void {
    for (const handle of this.#ttsHandles.values()) {
      handle.dispose();
    }
    this.#ttsHandles.clear();
    this.#playbackQueue.length = 0;
    this.#isAutoPlaying = false;
    this.#playingTurnId.set(null);
    this.#activeRecordingTurnId = null;
    this.#isRecording.set(false);
    this.#isNativeRecording.set(false);
    this.#isSending.set(false);
    this.#turns.set(resetConversation());
    console.log('[ConversationStore] reset');
  }
}
