import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { SplitId } from '../../domain/conversation/conversation-turn';
import { Language } from '../../domain/language/language';
import { SttPort, SttStreamEvent } from './stt.port';

const STEP_DELAY_MS = 300;

@Injectable()
export class DummySttAdapter implements SttPort {
  startCapture(): void {
    console.log('[DummySttAdapter] startCapture');
  }

  stopCapture(originSplit: SplitId, language: Language): Observable<SttStreamEvent> {
    console.log('[DummySttAdapter] stopCapture requested', {
      originSplit,
      language: language.code,
    });

    const sourceText = `[${language.label} speech placeholder]`;
    const translatedText = '[English translation placeholder]';

    return new Observable<SttStreamEvent>((subscriber) => {
      const timeouts: ReturnType<typeof setTimeout>[] = [];
      const schedule = (delayMs: number, event: SttStreamEvent) => {
        timeouts.push(setTimeout(() => subscriber.next(event), delayMs));
      };

      schedule(STEP_DELAY_MS, { type: 'source-delta', text: sourceText });

      if (originSplit === 'native-speaker') {
        timeouts.push(
          setTimeout(() => {
            subscriber.next({ type: 'source-done', sourceText });
            subscriber.complete();
          }, STEP_DELAY_MS * 2),
        );
        return () => timeouts.forEach(clearTimeout);
      }

      schedule(STEP_DELAY_MS * 2, { type: 'source-done', sourceText });
      schedule(STEP_DELAY_MS * 3, { type: 'translation-delta', text: translatedText });
      timeouts.push(
        setTimeout(() => {
          subscriber.next({ type: 'done', sourceText, translatedText });
          subscriber.complete();
        }, STEP_DELAY_MS * 4),
      );

      return () => timeouts.forEach(clearTimeout);
    });
  }
}
