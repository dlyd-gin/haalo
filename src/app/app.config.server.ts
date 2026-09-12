import { mergeApplicationConfig, ApplicationConfig } from '@angular/core';
import { provideServerRendering, withRoutes } from '@angular/ssr';
import { appConfig } from './app.config';
import { serverRoutes } from './app.routes.server';
import { DummySttAdapter } from './infrastructure/speech/dummy-stt.adapter';
import { DummyTtsAdapter } from './infrastructure/speech/dummy-tts.adapter';
import { STT_PORT } from './infrastructure/speech/stt.port';
import { TTS_PORT } from './infrastructure/speech/tts.port';

const serverConfig: ApplicationConfig = {
  providers: [
    provideServerRendering(withRoutes(serverRoutes)),
    // RealTtsAdapter uses URL.createObjectURL, a browser-only API — keep SSR
    // on the browser-API-free stub even though sendReply() only ever runs
    // post-hydration in practice.
    { provide: TTS_PORT, useClass: DummyTtsAdapter },
    // RealSttAdapter uses MediaRecorder/getUserMedia, also browser-only —
    // same reasoning as TTS_PORT above.
    { provide: STT_PORT, useClass: DummySttAdapter },
  ],
};

export const config = mergeApplicationConfig(appConfig, serverConfig);
