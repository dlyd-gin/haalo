const BYTES_PER_SAMPLE = 2; // 16-bit PCM
const WAV_HEADER_SIZE = 44;

function floatTo16BitPCM(samples: Float32Array): DataView {
  const view = new DataView(new ArrayBuffer(samples.length * BYTES_PER_SAMPLE));
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    const int16 = Math.round(clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff);
    view.setInt16(i * BYTES_PER_SAMPLE, int16, true);
  }
  return view;
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i++) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

function writeWavHeader(view: DataView, dataByteLength: number, sampleRate: number): void {
  const numChannels = 1;
  const bitsPerSample = BYTES_PER_SAMPLE * 8;
  const blockAlign = numChannels * BYTES_PER_SAMPLE;
  const byteRate = sampleRate * blockAlign;

  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataByteLength, true);
  writeAscii(view, 8, 'WAVE');
  writeAscii(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // fmt chunk size
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataByteLength, true);
}

// Pure PCM->WAV encoding: given mono float samples in [-1, 1] and a sample rate,
// produces a standard 16-bit PCM WAV file. Kept free of DOM/Web Audio types so it's
// independently unit-testable — decoding/downmixing the recorded audio into this
// shape is the caller's job.
export function encodeMonoWav(samples: Float32Array, sampleRate: number): Blob {
  const pcm = floatTo16BitPCM(samples);
  const buffer = new ArrayBuffer(WAV_HEADER_SIZE + pcm.byteLength);
  const view = new DataView(buffer);
  writeWavHeader(view, pcm.byteLength, sampleRate);
  new Uint8Array(buffer, WAV_HEADER_SIZE).set(new Uint8Array(pcm.buffer));
  return new Blob([buffer], { type: 'audio/wav' });
}
