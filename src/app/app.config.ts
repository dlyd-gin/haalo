import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideClientHydration, withEventReplay } from '@angular/platform-browser';
import { provideHttpClient, withFetch } from '@angular/common/http';
import { DOCUMENT_PORT } from './infrastructure/document/document.port';
import { RealDocumentAdapter } from './infrastructure/document/real-document.adapter';
import { RealSttAdapter } from './infrastructure/speech/real-stt.adapter';
import { RealTtsAdapter } from './infrastructure/speech/real-tts.adapter';
import { STT_PORT } from './infrastructure/speech/stt.port';
import { TTS_PORT } from './infrastructure/speech/tts.port';
import { WebAudioTtsAdapter } from './infrastructure/speech/web-audio-tts.adapter';
import { isWebKitOnly } from './infrastructure/speech/webkit';
import { RealTranslatorAdapter } from './infrastructure/translation/real-translator.adapter';
import { TRANSLATOR_PORT } from './infrastructure/translation/translator.port';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideClientHydration(withEventReplay()),
    provideHttpClient(withFetch()),
    { provide: STT_PORT, useClass: RealSttAdapter },
    // WebKit can't play the streaming TTS response through <audio src>, so it gets the
    // Web Audio adapter; everything else keeps the plain <audio> one (see webkit.ts).
    {
      provide: TTS_PORT,
      useFactory: () =>
        typeof navigator !== 'undefined' && isWebKitOnly(navigator.userAgent)
          ? new WebAudioTtsAdapter()
          : new RealTtsAdapter(),
    },
    { provide: TRANSLATOR_PORT, useClass: RealTranslatorAdapter },
    { provide: DOCUMENT_PORT, useClass: RealDocumentAdapter },
  ],
};
