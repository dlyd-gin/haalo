import { Pcm16Decoder, parseWavHeader } from './pcm-wav-stream';

// The same canonical 44-byte header tts-service streams: sizes left as 0xFFFFFFFF.
function streamingHeader(sampleRate: number, channels = 1): Uint8Array {
  const bytes = new Uint8Array(44);
  const view = new DataView(bytes.buffer);
  const ascii = (offset: number, text: string) =>
    [...text].forEach((ch, i) => view.setUint8(offset + i, ch.charCodeAt(0)));
  ascii(0, 'RIFF');
  view.setUint32(4, 0xffffffff, true);
  ascii(8, 'WAVE');
  ascii(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  ascii(36, 'data');
  view.setUint32(40, 0xffffffff, true);
  return bytes;
}

function int16Bytes(values: number[]): Uint8Array {
  const bytes = new Uint8Array(values.length * 2);
  const view = new DataView(bytes.buffer);
  values.forEach((v, i) => view.setInt16(i * 2, v, true));
  return bytes;
}

describe('parseWavHeader', () => {
  it('reads the format from a streaming header with unspecified sizes', () => {
    expect(parseWavHeader(streamingHeader(24000))).toEqual({ sampleRate: 24000, channels: 1, dataOffset: 44 });
  });

  it('returns null until the data chunk header has arrived', () => {
    const header = streamingHeader(24000);
    expect(parseWavHeader(header.subarray(0, 8))).toBeNull();
    expect(parseWavHeader(header.subarray(0, 30))).toBeNull();
    expect(parseWavHeader(header.subarray(0, 40))).toBeNull();
  });

  it('rejects bytes that are not a WAV file', () => {
    expect(() => parseWavHeader(new TextEncoder().encode('{"error":"nope"}'))).toThrow();
  });

  it('rejects non-16-bit PCM', () => {
    const header = streamingHeader(24000);
    new DataView(header.buffer).setUint16(34, 8, true);
    expect(() => parseWavHeader(header)).toThrow();
  });
});

describe('Pcm16Decoder', () => {
  it('converts int16 samples to floats in [-1, 1]', () => {
    const [samples] = new Pcm16Decoder(1).push(int16Bytes([0, 16384, -32768]));
    expect(Array.from(samples)).toEqual([0, 0.5, -1]);
  });

  it('carries an odd trailing byte over to the next push', () => {
    const decoder = new Pcm16Decoder(1);
    const bytes = int16Bytes([16384, -16384, 8192]);
    const [first] = decoder.push(bytes.subarray(0, 3));
    const [second] = decoder.push(bytes.subarray(3));
    expect(Array.from(first)).toEqual([0.5]);
    expect(Array.from(second)).toEqual([-0.5, 0.25]);
  });

  it('deinterleaves channels and keeps partial frames for later', () => {
    const decoder = new Pcm16Decoder(2);
    const bytes = int16Bytes([16384, -16384, 8192, -8192]);
    const [left1, right1] = decoder.push(bytes.subarray(0, 6));
    const [left2, right2] = decoder.push(bytes.subarray(6));
    expect([Array.from(left1), Array.from(right1)]).toEqual([[0.5], [-0.5]]);
    expect([Array.from(left2), Array.from(right2)]).toEqual([[0.25], [-0.25]]);
  });
});
