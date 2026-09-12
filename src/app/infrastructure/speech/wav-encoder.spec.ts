import { encodeMonoWav } from './wav-encoder';

function readAscii(view: DataView, offset: number, length: number): string {
  let text = '';
  for (let i = 0; i < length; i++) {
    text += String.fromCharCode(view.getUint8(offset + i));
  }
  return text;
}

describe('encodeMonoWav', () => {
  it('produces a Blob typed as audio/wav', () => {
    const blob = encodeMonoWav(new Float32Array([0, 0.5, -0.5]), 16000);
    expect(blob.type).toBe('audio/wav');
  });

  it('writes a valid RIFF/WAVE/fmt /data header', async () => {
    const sampleRate = 16000;
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1]);
    const blob = encodeMonoWav(samples, sampleRate);
    const view = new DataView(await blob.arrayBuffer());

    expect(readAscii(view, 0, 4)).toBe('RIFF');
    expect(readAscii(view, 8, 4)).toBe('WAVE');
    expect(readAscii(view, 12, 4)).toBe('fmt ');
    expect(readAscii(view, 36, 4)).toBe('data');

    const dataByteLength = samples.length * 2;
    expect(view.getUint32(4, true)).toBe(36 + dataByteLength);
    expect(view.getUint32(40, true)).toBe(dataByteLength);

    expect(view.getUint16(20, true)).toBe(1); // PCM
    expect(view.getUint16(22, true)).toBe(1); // mono
    expect(view.getUint32(24, true)).toBe(sampleRate);
    expect(view.getUint16(34, true)).toBe(16); // bits per sample
    expect(view.getUint32(28, true)).toBe(sampleRate * 2); // byte rate
    expect(view.getUint16(32, true)).toBe(2); // block align
  });

  it('encodes samples as 16-bit little-endian PCM', async () => {
    const blob = encodeMonoWav(new Float32Array([0, 0.5, -0.5]), 16000);
    const view = new DataView(await blob.arrayBuffer());

    expect(view.getInt16(44, true)).toBe(0);
    expect(view.getInt16(46, true)).toBe(Math.round(0.5 * 0x7fff));
    expect(view.getInt16(48, true)).toBe(Math.round(-0.5 * 0x8000));
  });

  it('clamps out-of-range samples to the int16 boundaries', async () => {
    const blob = encodeMonoWav(new Float32Array([1.5, -1.5]), 16000);
    const view = new DataView(await blob.arrayBuffer());

    expect(view.getInt16(44, true)).toBe(0x7fff);
    expect(view.getInt16(46, true)).toBe(-0x8000);
  });

  it('handles an empty sample array', async () => {
    const blob = encodeMonoWav(new Float32Array([]), 16000);
    const view = new DataView(await blob.arrayBuffer());

    expect(blob.size).toBe(44);
    expect(view.getUint32(40, true)).toBe(0);
  });
});
