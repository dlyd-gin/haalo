import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

export interface TranslationResult {
  readonly translatedText: string;
  readonly rephrasedText: string;
}

export type TranslationStreamEvent =
  | { readonly type: 'delta'; readonly text: string }
  | { readonly type: 'done'; readonly translatedText: string; readonly rephrasedText: string };

export interface TranslatorPort {
  translateStream(
    text: string,
    sourceLanguageCode: string,
    targetLanguageCode: string,
  ): Observable<TranslationStreamEvent>;
}

export const TRANSLATOR_PORT = new InjectionToken<TranslatorPort>('TRANSLATOR_PORT');
