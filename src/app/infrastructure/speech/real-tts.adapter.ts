import { Injectable } from '@angular/core';
import { fromEvent, map, Observable } from 'rxjs';
import { Language } from '../../domain/language/language';
import { TtsPort, TtsHandle } from './tts.port';

@Injectable()
export class RealTtsAdapter implements TtsPort {
  preload(text: string, language: Language): TtsHandle {
    const url = `/api/tts?text=${encodeURIComponent(text)}&language=${encodeURIComponent(language.code)}`;
    console.log('[RealTtsAdapter] preload requested', { text, language: language.code });

    const audio = new Audio();
    audio.preload = 'auto';
    audio.src = url;

    const errors: Observable<Error> = fromEvent(audio, 'error').pipe(
      map(() => new Error(audio.error?.message || 'audio playback failed')),
    );
    const ended: Observable<void> = fromEvent(audio, 'ended').pipe(map(() => undefined));

    return {
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
