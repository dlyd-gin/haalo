import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';
import { Language } from '../../domain/language/language';

export interface TtsHandle {
  preload(text: string, language: Language): void;
  play(): Promise<void>;
  pause(): void;
  readonly errors: Observable<Error>;
  readonly ended: Observable<void>;
  dispose(): void;
}

export interface TtsPort {
  // Call synchronously inside the user gesture that will later lead to autoplay — Safari only
  // lets an <audio> element play() outside a gesture if it was already played inside one.
  create(): TtsHandle;
}

export const TTS_PORT = new InjectionToken<TtsPort>('TTS_PORT');
