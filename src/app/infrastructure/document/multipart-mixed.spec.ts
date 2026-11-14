import { MultipartMixedParser, multipartBoundary } from './multipart-mixed';

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function body(boundary: string, binary: Uint8Array): Uint8Array {
  const head = encoder.encode(
    `--${boundary}\r\nContent-Type: application/octet-stream\r\nContent-Disposition: attachment; filename="a.docx"\r\n\r\n`,
  );
  const tail = encoder.encode(
    `\r\n--${boundary}\r\nContent-Type: application/json\r\n\r\n{"summary":"ok"}\r\n--${boundary}--\r\n`,
  );
  const out = new Uint8Array(head.length + binary.length + tail.length);
  out.set(head);
  out.set(binary, head.length);
  out.set(tail, head.length + binary.length);
  return out;
}

describe('multipartBoundary', () => {
  it('reads plain and quoted boundaries', () => {
    expect(multipartBoundary('multipart/mixed; boundary=abc123')).toBe('abc123');
    expect(multipartBoundary('multipart/mixed; boundary="a b"; charset=utf-8')).toBe('a b');
    expect(multipartBoundary('application/json')).toBeNull();
    expect(multipartBoundary(null)).toBeNull();
  });
});

describe('MultipartMixedParser', () => {
  // Binary bytes that include CR/LF and dashes, so the body can't be mistaken for framing.
  const binary = new Uint8Array([0, 13, 10, 45, 45, 255, 13, 10, 13, 10, 7]);

  it('parses both parts from a single chunk', () => {
    const parser = new MultipartMixedParser('b0und');
    const parts = parser.push(body('b0und', binary));

    expect(parts.length).toBe(2);
    expect(parts[0].headers['content-type']).toBe('application/octet-stream');
    expect(parts[0].headers['content-disposition']).toBe('attachment; filename="a.docx"');
    expect(Array.from(parts[0].body)).toEqual(Array.from(binary));
    expect(parts[1].headers['content-type']).toBe('application/json');
    expect(decoder.decode(parts[1].body)).toBe('{"summary":"ok"}');
    expect(parser.isDone).toBe(true);
  });

  it('gives the same parts when fed one byte at a time, each as soon as it is complete', () => {
    const parser = new MultipartMixedParser('b0und');
    const data = body('b0und', binary);
    const seen: number[] = [];
    const parts = [];
    for (let i = 0; i < data.length; i++) {
      for (const part of parser.push(data.subarray(i, i + 1))) {
        parts.push(part);
        seen.push(i);
      }
    }

    expect(parts.length).toBe(2);
    expect(Array.from(parts[0].body)).toEqual(Array.from(binary));
    expect(decoder.decode(parts[1].body)).toBe('{"summary":"ok"}');
    // The file part is emitted before the JSON part has arrived.
    expect(seen[0]).toBeLessThan(data.length - 30);
    expect(parser.isDone).toBe(true);
  });

  it('ignores a preamble and anything after the closing delimiter', () => {
    const parser = new MultipartMixedParser('x');
    const parts = parser.push(
      encoder.encode('preamble\r\n--x\r\nA: 1\r\n\r\nhello\r\n--x--\r\nepilogue\r\n--x\r\n\r\nlate'),
    );

    expect(parts.length).toBe(1);
    expect(parts[0].headers).toEqual({ a: '1' });
    expect(decoder.decode(parts[0].body)).toBe('hello');
    expect(parser.push(encoder.encode('\r\n--x--'))).toEqual([]);
  });
});
