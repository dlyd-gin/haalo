import { HttpErrorResponse } from '@angular/common/http';

async function readErrorBody(error: HttpErrorResponse): Promise<unknown> {
  if (error.error instanceof Blob) {
    const text = await error.error.text();
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return error.error;
}

function extractFromBody(body: unknown): string | undefined {
  if (typeof body === 'string' && body.trim().length > 0) {
    return body;
  }
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    if (typeof record['error'] === 'string') {
      return record['error'];
    }
    if (typeof record['detail'] === 'string') {
      return record['detail'];
    }
  }
  return undefined;
}

/**
 * Server error bodies aren't uniformly shaped or synchronously readable: JSON-typed
 * requests get a parsed `{ error }` / `{ detail }` object, but blob-typed requests
 * (e.g. TTS audio) always get the error body wrapped in a Blob by Angular's fetch
 * backend, regardless of status code, so it needs an async read to recover the text.
 */
export async function extractHttpErrorMessage(error: unknown): Promise<string> {
  if (error instanceof HttpErrorResponse) {
    const body = await readErrorBody(error);
    return extractFromBody(body) ?? error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}
