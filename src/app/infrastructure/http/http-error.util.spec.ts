import { HttpErrorResponse } from '@angular/common/http';
import { extractHttpErrorMessage } from './http-error.util';

describe('extractHttpErrorMessage', () => {
  it('reads the `error` field from a JSON-bodied HttpErrorResponse', async () => {
    const error = new HttpErrorResponse({
      status: 502,
      url: '/api/tts',
      error: { error: 'TTS service unavailable' },
    });

    expect(await extractHttpErrorMessage(error)).toBe('TTS service unavailable');
  });

  it('reads the `detail` field from a JSON-bodied HttpErrorResponse', async () => {
    const error = new HttpErrorResponse({
      status: 400,
      url: '/api/translate',
      error: { detail: 'unsupported target_language: fr' },
    });

    expect(await extractHttpErrorMessage(error)).toBe('unsupported target_language: fr');
  });

  it('reads the error text out of a Blob-bodied HttpErrorResponse', async () => {
    const blob = new Blob([JSON.stringify({ error: 'TTS service unavailable' })], {
      type: 'application/json',
    });
    const error = new HttpErrorResponse({ status: 502, url: '/api/tts', error: blob });

    expect(await extractHttpErrorMessage(error)).toBe('TTS service unavailable');
  });

  it('falls back to the generic HttpErrorResponse message when the body has no known field', async () => {
    const error = new HttpErrorResponse({ status: 500, url: '/api/tts', error: {} });

    expect(await extractHttpErrorMessage(error)).toContain('/api/tts');
  });

  it('returns the message of a plain Error', async () => {
    expect(await extractHttpErrorMessage(new Error('boom'))).toBe('boom');
  });

  it('stringifies anything else as a last resort', async () => {
    expect(await extractHttpErrorMessage('already a string')).toBe('already a string');
  });
});
