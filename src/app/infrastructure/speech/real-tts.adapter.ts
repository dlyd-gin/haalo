import { Injectable } from '@angular/core';
import { fromEvent, map, Observable } from 'rxjs';
import { Language } from '../../domain/language/language';
import { TtsPort, TtsHandle } from './tts.port';

// 8 samples of 16-bit mono silence — just enough of a real source for play() to be accepted
// while unlocking the element in create().
const SILENT_WAV =
  'data:audio/wav;base64,UklGRjQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YRAAAAAAAAAAAAAAAAAAAAAAAAAA';

@Injectable()
export class RealTtsAdapter implements TtsPort {
  create(): TtsHandle {
    const audio = new Audio();
    audio.preload = 'auto';

    // Safari rejects an unmuted play() outside a user gesture unless this same element was
    // already played inside one, so "touch" it now, while create() is still in the gesture.
    // play() and pause() must both run synchronously here; the play() promise rejecting
    // (AbortError) is expected — only the call itself matters.
    audio.src = SILENT_WAV;
    audio.play().catch(() => {});
    audio.pause();

    const errors: Observable<Error> = fromEvent(audio, 'error').pipe(
      map(() => new Error(audio.error?.message || 'audio playback failed')),
    );
    const ended: Observable<void> = fromEvent(audio, 'ended').pipe(map(() => undefined));

    return {
      preload: (text: string, language: Language) => {
        console.log('[RealTtsAdapter] preload requested', { text, language: language.code });
        audio.src = `/api/tts?text=${encodeURIComponent(text)}&language=${encodeURIComponent(language.code)}`;
      },
      play: () => audio.play(),
      pause: () => audio.pause(),
      errors,
      ended,
      dispose: () => {
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
      },
    };
  }
}
