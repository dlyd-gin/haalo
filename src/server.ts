import {
  AngularNodeAppEngine,
  createNodeRequestHandler,
  isMainModule,
  writeResponseToNodeResponse,
} from '@angular/ssr/node';
import express from 'express';
import { join } from 'node:path';
import { Readable } from 'node:stream';

const browserDistFolder = join(import.meta.dirname, '../browser');

const app = express();
const angularApp = new AngularNodeAppEngine();

const TTS_SERVICE_URL = process.env['TTS_SERVICE_URL'] ?? 'http://localhost:8000';
const TRANSLATOR_SERVICE_URL = process.env['TRANSLATOR_SERVICE_URL'] ?? 'http://localhost:8001';
const STT_SERVICE_URL = process.env['STT_SERVICE_URL'] ?? 'http://localhost:8002';
const DOCUMENT_SERVICE_URL = process.env['DOCUMENT_SERVICE_URL'] ?? 'http://localhost:8003';

app.get('/api/tts', async (req, res) => {
  try {
    const text = typeof req.query['text'] === 'string' ? req.query['text'] : '';
    const language = typeof req.query['language'] === 'string' ? req.query['language'] : '';
    const upstreamUrl = new URL(`${TTS_SERVICE_URL}/synthesize`);
    upstreamUrl.searchParams.set('text', text);
    upstreamUrl.searchParams.set('language', language);

    const upstream = await fetch(upstreamUrl, {
      method: 'GET',
      signal: AbortSignal.timeout(60_000),
    });

    res.status(upstream.status);
    const contentType = upstream.headers.get('content-type');
    if (contentType) {
      res.setHeader('Content-Type', contentType);
    }

    if (!upstream.body) {
      res.end();
      return;
    }
    Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream).pipe(res);
  } catch (err) {
    console.error('[tts-proxy] upstream request failed', err);
    res.status(502).json({ error: 'TTS service unavailable' });
  }
});

app.post('/api/stt', express.raw({ type: '*/*', limit: '25mb' }), async (req, res) => {
  try {
    const language = typeof req.query['language'] === 'string' ? req.query['language'] : '';
    const upstreamUrl = new URL(`${STT_SERVICE_URL}/transcribe`);
    upstreamUrl.searchParams.set('language', language);

    const upstream = await fetch(upstreamUrl, {
      method: 'POST',
      body: req.body,
      signal: AbortSignal.timeout(60_000),
    });

    res.status(upstream.status);
    const contentType = upstream.headers.get('content-type');
    if (contentType) {
      res.setHeader('Content-Type', contentType);
    }

    if (!upstream.body) {
      res.end();
      return;
    }
    Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream).pipe(res);
  } catch (err) {
    console.error('[stt-proxy] upstream request failed', err);
    res.status(502).json({ error: 'STT service unavailable' });
  }
});

app.post('/api/translate', express.json(), async (req, res) => {
  try {
    const upstream = await fetch(`${TRANSLATOR_SERVICE_URL}/translate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
      signal: AbortSignal.timeout(60_000),
    });

    res.status(upstream.status);
    const contentType = upstream.headers.get('content-type');
    if (contentType) {
      res.setHeader('Content-Type', contentType);
    }

    if (!upstream.body) {
      res.end();
      return;
    }
    Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream).pipe(res);
  } catch (err) {
    console.error('[translate-proxy] upstream request failed', err);
    res.status(502).json({ error: 'Translator service unavailable' });
  }
});

app.post('/api/pdf/analyze', express.raw({ type: '*/*', limit: '25mb' }), async (req, res) => {
  try {
    const upstream = await fetch(`${DOCUMENT_SERVICE_URL}/analyze`, {
      method: 'POST',
      body: req.body,
      signal: AbortSignal.timeout(60_000),
    });

    res.status(upstream.status);
    const contentType = upstream.headers.get('content-type');
    if (contentType) {
      res.setHeader('Content-Type', contentType);
    }

    if (!upstream.body) {
      res.end();
      return;
    }
    Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream).pipe(res);
  } catch (err) {
    console.error('[pdf-proxy] upstream request failed', err);
    res.status(502).json({ error: 'PDF service unavailable' });
  }
});

// Pass-through for document-service's multipart endpoints: the raw body is forwarded with its own
// Content-Type (which carries the multipart boundary), so no multipart parsing happens here.
function proxyDocument(upstreamPath: string, timeoutMs: number): express.RequestHandler {
  return async (req, res) => {
    try {
      const contentType = req.headers['content-type'];
      const upstream = await fetch(`${DOCUMENT_SERVICE_URL}${upstreamPath}`, {
        method: 'POST',
        headers: contentType ? { 'Content-Type': contentType } : {},
        body: req.body,
        signal: AbortSignal.timeout(timeoutMs),
      });

      res.status(upstream.status);
      for (const header of ['content-type', 'content-disposition']) {
        const value = upstream.headers.get(header);
        if (value) {
          res.setHeader(header, value);
        }
      }

      if (!upstream.body) {
        res.end();
        return;
      }
      Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream).pipe(res);
    } catch (err) {
      console.error(`[document-proxy] ${upstreamPath} upstream request failed`, err);
      res.status(502).json({ error: 'Document service unavailable' });
    }
  };
}

const documentBody = express.raw({ type: '*/*', limit: '25mb' });
app.post('/api/document/extract-words', documentBody, proxyDocument('/extract-words', 300_000));
// OCR through a VLM is slow.
app.post('/api/document/image-to-words', documentBody, proxyDocument('/image-to-words', 300_000));
// Two LLM calls: picking the suggestions, then summarizing them.
app.post(
  '/api/document/giveme-suggestion',
  documentBody,
  proxyDocument('/giveme-suggestion', 600_000),
);
// Same, straight on a PDF (no docx conversion); answers 422 when the PDF has no usable text layer.
app.post(
  '/api/document/giveme-suggestion-pdf',
  documentBody,
  proxyDocument('/giveme-suggestion-pdf', 600_000),
);
// Same, straight on an image: OCR, then the suggestions highlighted on the image (two VLM calls).
app.post(
  '/api/document/giveme-suggestion-image',
  documentBody,
  proxyDocument('/giveme-suggestion-image', 600_000),
);

/**
 * Serve static files from /browser
 */
app.use(
  express.static(browserDistFolder, {
    maxAge: '1y',
    index: false,
    redirect: false,
  }),
);

/**
 * Handle all other requests by rendering the Angular application.
 */
app.use((req, res, next) => {
  angularApp
    .handle(req)
    .then((response) => (response ? writeResponseToNodeResponse(response, res) : next()))
    .catch(next);
});

/**
 * Start the server if this module is the main entry point, or it is ran via PM2.
 * The server listens on the port defined by the `PORT` environment variable, or defaults to 4000.
 */
if (isMainModule(import.meta.url) || process.env['pm_id']) {
  const port = process.env['PORT'] || 4000;
  app.listen(port, (error) => {
    if (error) {
      throw error;
    }

    console.log(`Node Express server listening on http://localhost:${port}`);
  });
}

/**
 * Request handler used by the Angular CLI (for dev-server and during build) or Firebase Cloud Functions.
 */
export const reqHandler = createNodeRequestHandler(app);
