export interface MultipartPart {
  // Header names are lower-cased.
  readonly headers: Readonly<Record<string, string>>;
  readonly body: Uint8Array;
}

export function multipartBoundary(contentType: string | null): string | null {
  const match = contentType?.match(/boundary="?([^";]+)"?/i);
  return match ? match[1] : null;
}

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const CRLF = encoder.encode('\r\n');
const HEADER_END = encoder.encode('\r\n\r\n');

function indexOf(haystack: Uint8Array, needle: Uint8Array, from: number): number {
  outer: for (let i = Math.max(from, 0); i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) {
        continue outer;
      }
    }
    return i;
  }
  return -1;
}

function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out = new Uint8Array(a.length + b.length);
  out.set(a);
  out.set(b, a.length);
  return out;
}

function parsePart(raw: Uint8Array): MultipartPart {
  const split = indexOf(raw, HEADER_END, 0);
  const head = split === -1 ? raw : raw.subarray(0, split);
  const body = split === -1 ? new Uint8Array() : raw.slice(split + HEADER_END.length);
  const headers: Record<string, string> = {};
  for (const line of decoder.decode(head).split('\r\n')) {
    const colon = line.indexOf(':');
    if (colon > 0) {
      headers[line.slice(0, colon).trim().toLowerCase()] = line.slice(colon + 1).trim();
    }
  }
  return { headers, body };
}

/**
 * Incremental multipart/mixed (RFC 2046) parser: push() the response body's chunks as they arrive
 * and it returns each part once the delimiter after it has been seen, so an early part (e.g. a
 * file) is usable before a later, slower one has been sent.
 */
export class MultipartMixedParser {
  // Every delimiter is CRLF + "--" + boundary; a leading CRLF is fed in so the first one (at the
  // very start of the body, without a CRLF) matches the same pattern.
  readonly #delimiter: Uint8Array;
  #buffer: Uint8Array = CRLF;
  #inPart = false;
  #searchFrom = 0;
  #done = false;

  constructor(boundary: string) {
    this.#delimiter = encoder.encode(`\r\n--${boundary}`);
  }

  get isDone(): boolean {
    return this.#done;
  }

  push(chunk: Uint8Array): MultipartPart[] {
    if (this.#done) {
      return [];
    }
    this.#buffer = concat(this.#buffer, chunk);
    const parts: MultipartPart[] = [];

    while (!this.#done) {
      if (!this.#inPart) {
        const start = indexOf(this.#buffer, this.#delimiter, 0);
        if (start === -1) {
          break;
        }
        this.#buffer = this.#buffer.slice(start + this.#delimiter.length);
        this.#inPart = true;
        this.#searchFrom = 0;
      }
      // Right after a delimiter: "--" closes the body, CRLF opens a part.
      if (this.#buffer.length < 2) {
        break;
      }
      if (this.#buffer[0] === 0x2d && this.#buffer[1] === 0x2d) {
        this.#done = true;
        break;
      }
      const end = indexOf(this.#buffer, this.#delimiter, Math.max(this.#searchFrom, 2));
      if (end === -1) {
        // Resume where a delimiter split across chunks could still start.
        this.#searchFrom = this.#buffer.length - this.#delimiter.length + 1;
        break;
      }
      parts.push(parsePart(this.#buffer.subarray(2, end)));
      this.#buffer = this.#buffer.slice(end + this.#delimiter.length);
      this.#searchFrom = 0;
    }
    return parts;
  }
}
