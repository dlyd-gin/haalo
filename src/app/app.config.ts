import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideClientHydration, withEventReplay } from '@angular/platform-browser';
import { provideHttpClient, withFetch } from '@angular/common/http';
import { RealSttAdapter } from './infrastructure/speech/real-stt.adapter';
import { RealTtsAdapter } from './infrastructure/speech/real-tts.adapter';
import { STT_PORT } from './infrastructure/speech/stt.port';
import { TTS_PORT } from './infrastructure/speech/tts.port';
import { RealTranslatorAdapter } from './infrastructure/translation/real-translator.adapter';
import { TRANSLATOR_PORT } from './infrastructure/translation/translator.port';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideClientHydration(withEventReplay()),
    provideHttpClient(withFetch()),
    { provide: STT_PORT, useClass: RealSttAdapter },
    { provide: TTS_PORT, useClass: RealTtsAdapter },
    { provide: TRANSLATOR_PORT, useClass: RealTranslatorAdapter },
  ],
};
