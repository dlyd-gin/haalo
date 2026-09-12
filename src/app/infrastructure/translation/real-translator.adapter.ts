import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { TranslatorPort, TranslationStreamEvent } from './translator.port';

type TranslateSseEvent =
  | { type: 'delta'; text: string }
  | { type: 'done'; answer: string; rephrased_text: string }
  | { type: 'error'; message: string };

// translator-service uses its own language-code dialect ('jp' for Japanese) that differs from
// the app's canonical ISO 639-1 codes used everywhere else ('ja') — translate at this boundary
// only, so the rest of the app doesn't need to know about it.
const TRANSLATOR_SERVICE_LANGUAGE_CODES: Record<string, string> = {
  en: 'en',
  ja: 'jp',
};

function toTranslatorServiceCode(languageCode: string): string {
  return TRANSLATOR_SERVICE_LANGUAGE_CODES[languageCode] ?? languageCode;
}

async function extractErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === 'object') {
      const record = body as Record<string, unknown>;
      if (typeof record['error'] === 'string') {
        return record['error'];
      }
      if (typeof record['detail'] === 'string') {
        return record['detail'];
      }
    }
  } catch {
    // body wasn't JSON — fall through to statusText below.
  }
  return response.statusText || `translate request failed: ${response.status}`;
}

@Injectable()
export class RealTranslatorAdapter implements TranslatorPort {
  translateStream(
    text: string,
    sourceLanguageCode: string,
    targetLanguageCode: string,
  ): Observable<TranslationStreamEvent> {
    return new Observable<TranslationStreamEvent>((subscriber) => {
      const controller = new AbortController();

      (async () => {
        const response = await fetch('/api/translate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text,
            source_language: toTranslatorServiceCode(sourceLanguageCode),
            target_language: toTranslatorServiceCode(targetLanguageCode),
          }),
          signal: controller.signal,
        });

        if (!response.ok || !response.body) {
          throw new Error(await extractErrorMessage(response));
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });

          const frames = buffer.split('\n\n');
          buffer = frames.pop() ?? '';

          for (const frame of frames) {
            const payload = frame.replace(/^data: /, '').trim();
            if (!payload) {
              continue;
            }
            const event = JSON.parse(payload) as TranslateSseEvent;
            if (event.type === 'delta') {
              subscriber.next({ type: 'delta', text: event.text });
            } else if (event.type === 'done') {
              subscriber.next({
                type: 'done',
                translatedText: event.answer,
                rephrasedText: event.rephrased_text,
              });
              subscriber.complete();
              return;
            } else {
              throw new Error(event.message);
            }
          }
        }

        subscriber.complete();
      })().catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        subscriber.error(error instanceof Error ? error : new Error(String(error)));
      });

      return () => controller.abort();
    });
  }
}
