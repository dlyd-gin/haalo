// Pure helpers for reading tts-service's streaming WAV (16-bit PCM, sizes declared as
// 0xFFFFFFFF since the total length isn't known up front) incrementally off a fetch body.
// Kept free of DOM/Web Audio types so they're independently unit-testable — turning the
// decoded samples into AudioBuffers is WebAudioTtsAdapter's job.

export interface WavStreamFormat {
  sampleRate: number;
  channels: number;
  // Byte offset of the first PCM sample, i.e. right after the `data` chunk header.
  dataOffset: number;
}

function readAscii(bytes: Uint8Array, offset: number, length: number): string {
  return String.fromCharCode(...bytes.subarray(offset, offset + length));
}

// Parses the RIFF header from the start of the stream. Returns null while not enough bytes
// have arrived yet to reach the `data` chunk; throws if the bytes aren't a 16-bit PCM WAV.
// The RIFF and data chunk sizes are deliberately ignored — the streaming header leaves them
// unspecified.
export function parseWavHeader(bytes: Uint8Array): WavStreamFormat | null {
  if (bytes.length < 12) {
    return null;
  }
  if (readAscii(bytes, 0, 4) !== 'RIFF' || readAscii(bytes, 8, 4) !== 'WAVE') {
    throw new Error('tts stream is not a WAV file');
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let format: { sampleRate: number; channels: number } | null = null;
  let offset = 12;
  while (offset + 8 <= bytes.length) {
    const id = readAscii(bytes, offset, 4);
    const size = view.getUint32(offset + 4, true);
    if (id === 'data') {
      if (!format) {
        throw new Error('tts stream has no fmt chunk before its data');
      }
      return { ...format, dataOffset: offset + 8 };
    }
    if (offset + 8 + size > bytes.length) {
      return null; // this chunk's body hasn't fully arrived yet
    }
    if (id === 'fmt ') {
      const audioFormat = view.getUint16(offset + 8, true);
      const channels = view.getUint16(offset + 10, true);
      const sampleRate = view.getUint32(offset + 12, true);
      const bitsPerSample = view.getUint16(offset + 22, true);
      if (audioFormat !== 1 || bitsPerSample !== 16 || channels < 1) {
        throw new Error('tts stream is not 16-bit PCM');
      }
      format = { sampleRate, channels };
    }
    offset += 8 + size + (size % 2); // RIFF chunks are padded to an even size
  }
  return null;
}

// Converts little-endian 16-bit PCM into per-channel float samples in [-1, 1]. Network chunk
// boundaries are arbitrary, so a trailing partial frame (even a single odd byte) is carried
// over and completed by the next push().
export class Pcm16Decoder {
  readonly #channels: number;
  #pending = new Uint8Array(0);

  constructor(channels: number) {
    this.#channels = channels;
  }

  push(bytes: Uint8Array): Float32Array[] {
    let input = bytes;
    if (this.#pending.length) {
      input = new Uint8Array(this.#pending.length + bytes.length);
      input.set(this.#pending);
      input.set(bytes, this.#pending.length);
    }
    const frameBytes = 2 * this.#channels;
    const frames = Math.floor(input.length / frameBytes);
    const usable = frames * frameBytes;
    this.#pending = input.slice(usable);

    const view = new DataView(input.buffer, input.byteOffset, usable);
    const out = Array.from({ length: this.#channels }, () => new Float32Array(frames));
    for (let frame = 0; frame < frames; frame++) {
      for (let channel = 0; channel < this.#channels; channel++) {
        out[channel][frame] = view.getInt16((frame * this.#channels + channel) * 2, true) / 0x8000;
      }
    }
    return out;
  }
}
