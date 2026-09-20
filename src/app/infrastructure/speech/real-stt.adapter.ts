import { Injectable, inject } from '@angular/core';
import { Observable, Subscriber } from 'rxjs';
import { SplitId } from '../../domain/conversation/conversation-turn';
import { Language } from '../../domain/language/language';
import { TRANSLATOR_PORT } from '../translation/translator.port';
import { SttPort, SttStreamEvent } from './stt.port';
import { encodeMonoWav } from './wav-encoder';

// The native-speaker panel is always English — mirrors ConversationStore's
// NATIVE_LANGUAGE_CODE (the foreign speaker's transcript always translates to English).
const NATIVE_LANGUAGE_CODE = 'en';

type SttSseEvent =
  | { type: 'delta'; text: string }
  | { type: 'done'; text: string; language: string }
  | { type: 'error'; message: string };

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
  return response.statusText || `transcribe request failed: ${response.status}`;
}

@Injectable()
export class RealSttAdapter implements SttPort {
  #translator = inject(TRANSLATOR_PORT);

  #mediaRecorder: MediaRecorder | null = null;
  #mediaStream: MediaStream | null = null;
  #chunks: Blob[] = [];
  #captureReady: Promise<void> | null = null;

  startCapture(): void {
    console.log('[RealSttAdapter] startCapture');
    this.#chunks = [];
    this.#captureReady = navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      this.#mediaStream = stream;
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.#chunks.push(event.data);
        }
      };
      this.#mediaRecorder = recorder;
      recorder.start();
    });
    // Swallow here — stopCapture() awaits captureReady and surfaces the rejection there,
    // where it can be routed into the Observable's error channel.
    this.#captureReady.catch(() => undefined);
  }

  stopCapture(originSplit: SplitId, language: Language): Observable<SttStreamEvent> {
    console.log('[RealSttAdapter] stopCapture requested', { originSplit, language: language.code });

    return new Observable<SttStreamEvent>((subscriber) => {
      const controller = new AbortController();

      (async () => {
        await this.#captureReady;
        const recorder = this.#mediaRecorder;
        const stream = this.#mediaStream;
        if (!recorder || !stream) {
          throw new Error('microphone capture was not started');
        }

        const mimeType = recorder.mimeType;
        const stopped = new Promise<void>((resolve) => {
          recorder.addEventListener('stop', () => resolve(), { once: true });
        });
        recorder.stop();
        await stopped;
        stream.getTracks().forEach((track) => track.stop());
        this.#mediaRecorder = null;
        this.#mediaStream = null;
        this.#captureReady = null;

        const blob = new Blob(this.#chunks, { type: mimeType });
        this.#chunks = [];

        // stt-service only decodes WAV/MP3/FLAC/Vorbis without a system ffmpeg binary —
        // WebM/Opus (Chrome) and M4A/AAC (Safari), what MediaRecorder actually produces,
        // require ffmpeg on PATH. Re-encode to WAV here so ffmpeg is never needed.
        const audioContext = new AudioContext();
        let wavBlob: Blob;
        try {
          const arrayBuffer = await blob.arrayBuffer();
          const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
          const samples = this.#downmixToMono(audioBuffer);
          wavBlob = encodeMonoWav(samples, audioBuffer.sampleRate);
        } finally {
          await audioContext.close();
        }

        const response = await fetch(`/api/stt?language=${encodeURIComponent(language.code)}`, {
          method: 'POST',
          headers: { 'Content-Type': 'audio/wav' },
          body: wavBlob,
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
            const event = JSON.parse(payload) as SttSseEvent;

            if (event.type === 'delta') {
              subscriber.next({ type: 'source-delta', text: event.text });
            } else if (event.type === 'done') {
              subscriber.next({ type: 'source-done', sourceText: event.text });
              if (originSplit === 'native-speaker') {
                subscriber.complete();
                return;
              }
              await this.#translateAndComplete(subscriber, event.text, language, controller.signal);
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

  #downmixToMono(audioBuffer: AudioBuffer): Float32Array {
    if (audioBuffer.numberOfChannels === 1) {
      return audioBuffer.getChannelData(0);
    }
    const mixed = new Float32Array(audioBuffer.length);
    for (let channel = 0; channel < audioBuffer.numberOfChannels; channel++) {
      const data = audioBuffer.getChannelData(channel);
      for (let i = 0; i < data.length; i++) {
        mixed[i] += data[i] / audioBuffer.numberOfChannels;
      }
    }
    return mixed;
  }

  // Chains the existing translator-service into the same stream once the source
  // transcript is final — stt-service only transcribes (see its README's Scope note).
  #translateAndComplete(
    subscriber: Subscriber<SttStreamEvent>,
    sourceText: string,
    language: Language,
    signal: AbortSignal,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const subscription = this.#translator
        .translateStream(sourceText, language.code, NATIVE_LANGUAGE_CODE)
        .subscribe({
          next: (event) => {
            if (event.type === 'delta') {
              subscriber.next({ type: 'translation-delta', text: event.text });
              return;
            }
            subscriber.next({ type: 'done', sourceText, translatedText: event.translatedText });
            subscriber.complete();
            resolve();
          },
          error: (error: unknown) => {
            subscriber.error(error instanceof Error ? error : new Error(String(error)));
            reject(error instanceof Error ? error : new Error(String(error)));
          },
        });
      signal.addEventListener('abort', () => subscription.unsubscribe());
    });
  }
}
