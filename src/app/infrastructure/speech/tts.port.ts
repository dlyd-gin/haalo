import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';
import { Language } from '../../domain/language/language';

export interface TtsHandle {
  play(): Promise<void>;
  pause(): void;
  readonly errors: Observable<Error>;
  readonly ended: Observable<void>;
  dispose(): void;
}

export interface TtsPort {
  preload(text: string, language: Language): TtsHandle;
}

export const TTS_PORT = new InjectionToken<TtsPort>('TTS_PORT');
