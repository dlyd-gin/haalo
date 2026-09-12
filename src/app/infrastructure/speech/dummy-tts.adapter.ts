import { Injectable } from '@angular/core';
import { map, NEVER, Observable, timer } from 'rxjs';
import { Language } from '../../domain/language/language';
import { TtsPort, TtsHandle } from './tts.port';

// A real audio element only ever fires 'ended' asynchronously (a genuine browser event) —
// use a timer rather than a synchronous observable so callers can't be called back before
// their own preload() call has even returned.
const SIMULATED_PLAYBACK_MS = 300;

@Injectable()
export class DummyTtsAdapter implements TtsPort {
  preload(text: string, language: Language): TtsHandle {
    console.log('[DummyTtsAdapter] preload requested', { text, language: language.code });

    return {
      play: () => Promise.resolve(),
      pause: () => {},
      errors: NEVER as Observable<Error>,
      ended: timer(SIMULATED_PLAYBACK_MS).pipe(map(() => undefined)),
      dispose: () => {},
    };
  }
}
