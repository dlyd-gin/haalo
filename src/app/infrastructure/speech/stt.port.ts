import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';
import { SplitId } from '../../domain/conversation/conversation-turn';
import { Language } from '../../domain/language/language';

export type SttStreamEvent =
  | { readonly type: 'source-delta'; readonly text: string }
  | { readonly type: 'source-done'; readonly sourceText: string }
  | { readonly type: 'translation-delta'; readonly text: string }
  | { readonly type: 'done'; readonly sourceText: string; readonly translatedText: string }
  | { readonly type: 'error'; readonly message: string };

export interface SttPort {
  startCapture(): void;
  stopCapture(originSplit: SplitId, language: Language): Observable<SttStreamEvent>;
}

export const STT_PORT = new InjectionToken<SttPort>('STT_PORT');
