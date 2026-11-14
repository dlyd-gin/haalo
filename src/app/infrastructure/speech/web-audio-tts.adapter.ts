import { Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { Language } from '../../domain/language/language';
import { Pcm16Decoder, parseWavHeader } from './pcm-wav-stream';
import { TtsHandle, TtsPort } from './tts.port';

// TTS for WebKit browsers (see webkit.ts): WebKit won't play the streaming /api/tts response
// through <audio src> (no byte ranges, no known length), so this reads the stream with fetch
// and plays its PCM through Web Audio instead, chunk by chunk as it arrives — playback still
// starts before synthesis has finished, like the <audio> path does in Chrome.
@Injectable()
export class WebAudioTtsAdapter implements TtsPort {
  #context: AudioContext | null = null;

  create(): TtsHandle {
    const context = (this.#context ??= new AudioContext());
    // create() runs inside the send gesture — resuming the context there is what unlocks
    // Web Audio output in Safari for the autoplay that happens later, outside the gesture.
    context.resume().catch(() => {});
    return new WebAudioTtsHandle(context);
  }
}

interface ScheduledChunk {
  source: AudioBufferSourceNode;
  index: number; // into #buffers
  startTime: number; // context time the source starts at
  offset: number; // seconds into the buffer the source starts from
}

class WebAudioTtsHandle implements TtsHandle {
  readonly #context: AudioContext;
  readonly #abort = new AbortController();
  readonly #errors = new Subject<Error>();
  readonly #ended = new Subject<void>();
  readonly errors: Observable<Error> = this.#errors.asObservable();
  readonly ended: Observable<void> = this.#ended.asObservable();

  #buffers: AudioBuffer[] = [];
  #downloadDone = false;

  #playing = false;
  // Set by play() before it awaits resume(), cleared by pause() — a pause that lands while
  // play() is still waiting must win, not be overridden once the await finishes.
  #playRequested = false;
  // Bumped whenever scheduled sources are stopped, so their late `onended` callbacks
  // aren't mistaken for the clip finishing naturally.
  #generation = 0;
  #scheduled: ScheduledChunk[] = [];
  #nextIndex = 0;
  #nextOffset = 0;
  #nextStartTime = 0;

  // Where the next play() starts from — moved by pause(), reset to the start once the clip ends.
  #resumeIndex = 0;
  #resumeOffset = 0;

  constructor(context: AudioContext) {
    this.#context = context;
  }

  preload(text: string, language: Language): void {
    console.log('[WebAudioTtsAdapter] preload requested', { text, language: language.code });
    const url = `/api/tts?text=${encodeURIComponent(text)}&language=${encodeURIComponent(language.code)}`;
    void this.#download(url);
  }

  async play(): Promise<void> {
    this.#playRequested = true;
    await this.#context.resume();
    if (!this.#playRequested || this.#playing) {
      return;
    }
    this.#playing = true;
    this.#nextIndex = this.#resumeIndex;
    this.#nextOffset = this.#resumeOffset;
    this.#nextStartTime = 0;
    this.#scheduleBuffered();
    this.#checkEnded();
  }

  pause(): void {
    this.#playRequested = false;
    if (!this.#playing) {
      return;
    }
    const now = this.#context.currentTime;
    const current = this.#scheduled.find(
      (chunk) => now < chunk.startTime + this.#buffers[chunk.index].duration - chunk.offset,
    );
    if (current) {
      this.#resumeIndex = current.index;
      this.#resumeOffset = current.offset + Math.max(0, now - current.startTime);
    } else {
      // Everything scheduled has already played — download is behind; resume at the next chunk.
      this.#resumeIndex = this.#nextIndex;
      this.#resumeOffset = 0;
    }
    this.#stopScheduled();
  }

  dispose(): void {
    this.#playRequested = false;
    this.#abort.abort();
    this.#stopScheduled();
    this.#buffers = [];
  }

  async #download(url: string): Promise<void> {
    try {
      const response = await fetch(url, { signal: this.#abort.signal });
      if (!response.ok || !response.body) {
        throw new Error(`tts request failed (${response.status})`);
      }
      const reader = response.body.getReader();
      let headerBytes = new Uint8Array(0);
      let decoder: Pcm16Decoder | null = null;
      let sampleRate = 0;

      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        if (decoder) {
          this.#append(decoder.push(value), sampleRate);
          continue;
        }
        // Still collecting the WAV header, which may be split across network chunks.
        const joined = new Uint8Array(headerBytes.length + value.length);
        joined.set(headerBytes);
        joined.set(value, headerBytes.length);
        headerBytes = joined;
        const format = parseWavHeader(headerBytes);
        if (format) {
          decoder = new Pcm16Decoder(format.channels);
          sampleRate = format.sampleRate;
          this.#append(decoder.push(headerBytes.subarray(format.dataOffset)), sampleRate);
        }
      }

      this.#downloadDone = true;
      if (!this.#buffers.length) {
        throw new Error('tts stream contained no audio');
      }
      this.#checkEnded();
    } catch (error) {
      if (this.#abort.signal.aborted) {
        return; // disposed — nobody is listening any more
      }
      this.#stopScheduled();
      this.#errors.next(error instanceof Error ? error : new Error(String(error)));
    }
  }

  #append(channels: Float32Array[], sampleRate: number): void {
    const length = channels[0]?.length ?? 0;
    if (!length) {
      return;
    }
    const buffer = this.#context.createBuffer(channels.length, length, sampleRate);
    channels.forEach((samples, channel) => buffer.getChannelData(channel).set(samples));
    this.#buffers.push(buffer);
    this.#scheduleBuffered();
  }

  // Schedules every downloaded-but-unscheduled chunk back to back. If the download fell behind
  // playback, the next chunk simply starts "now" — a short gap rather than a failure.
  #scheduleBuffered(): void {
    while (this.#playing && this.#nextIndex < this.#buffers.length) {
      const index = this.#nextIndex++;
      const buffer = this.#buffers[index];
      const offset = Math.min(this.#nextOffset, buffer.duration);
      const startTime = Math.max(this.#context.currentTime, this.#nextStartTime);

      const source = this.#context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.#context.destination);
      const generation = this.#generation;
      source.onended = () => this.#onSourceEnded(source, generation);
      source.start(startTime, offset);

      this.#scheduled.push({ source, index, startTime, offset });
      this.#nextStartTime = startTime + buffer.duration - offset;
      this.#nextOffset = 0;
    }
  }

  #onSourceEnded(source: AudioBufferSourceNode, generation: number): void {
    if (generation !== this.#generation) {
      return;
    }
    this.#scheduled = this.#scheduled.filter((chunk) => chunk.source !== source);
    this.#checkEnded();
  }

  // The clip has ended once the download is complete and every chunk has played out.
  #checkEnded(): void {
    if (
      !this.#playing ||
      !this.#downloadDone ||
      this.#scheduled.length ||
      this.#nextIndex < this.#buffers.length
    ) {
      return;
    }
    this.#playing = false;
    this.#resumeIndex = 0;
    this.#resumeOffset = 0;
    this.#ended.next();
  }

  #stopScheduled(): void {
    this.#generation++;
    this.#playing = false;
    for (const { source } of this.#scheduled) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // already stopped
      }
      source.disconnect();
    }
    this.#scheduled = [];
  }
}
