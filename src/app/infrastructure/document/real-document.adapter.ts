import { Injectable } from '@angular/core';
import { Observable, Subscriber } from 'rxjs';
import { extractFetchErrorMessage } from '../http/http-error.util';
import {
  DocumentPort,
  DocumentSuggestionEvent,
  attachmentKind,
  unsupportedAttachmentMessage,
} from './document.port';
import { MultipartMixedParser, MultipartPart, multipartBoundary } from './multipart-mixed';

type SummaryPayload = { summary?: string; error?: string; highlights?: string[] };

const decoder = new TextDecoder();

function stemOf(fileName: string): string {
  const dot = fileName.lastIndexOf('.');
  return (dot > 0 ? fileName.slice(0, dot) : fileName) || 'document';
}

function fileNameOf(contentDisposition: string | undefined, fallback: string): string {
  const encoded = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1]);
    } catch {
      // malformed escape — try the plain form below.
    }
  }
  return contentDisposition?.match(/filename="?([^";]+)"?/i)?.[1] ?? fallback;
}

async function postForm(path: string, form: FormData, signal: AbortSignal): Promise<Response> {
  const response = await fetch(path, { method: 'POST', body: form, signal });
  if (!response.ok) {
    throw new Error(await extractFetchErrorMessage(response));
  }
  return response;
}

@Injectable()
export class RealDocumentAdapter implements DocumentPort {
  suggest(file: File, instruction: string): Observable<DocumentSuggestionEvent> {
    return new Observable<DocumentSuggestionEvent>((subscriber) => {
      const controller = new AbortController();

      (async () => {
        const { response, sourceName } = await this.#requestSuggestion(
          file,
          instruction,
          controller.signal,
        );

        const boundary = multipartBoundary(response.headers.get('content-type'));
        if (!boundary || !response.body) {
          throw new Error('document service returned an unexpected response');
        }
        const parser = new MultipartMixedParser(boundary);
        const reader = response.body.getReader();
        let partIndex = 0;
        while (!parser.isDone) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          for (const part of parser.push(value)) {
            this.#emitPart(subscriber, part, partIndex++, sourceName);
          }
        }
        if (partIndex < 2) {
          throw new Error('document service response ended early');
        }
        subscriber.complete();
      })().catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        subscriber.error(error instanceof Error ? error : new Error(String(error)));
      });

      return () => controller.abort();
    });
  }

  // PDFs and images are highlighted as is (giveme-suggestion-pdf / -image). When that endpoint can't
  // (PDF: 422 scanned or rotated; image: 422 no text or a 5xx OCR failure), the file goes through
  // giveme-suggestion as a .docx instead — as does a .docx itself.
  async #requestSuggestion(
    file: File,
    instruction: string,
    signal: AbortSignal,
  ): Promise<{ response: Response; sourceName: string }> {
    const kind = attachmentKind(file);
    if (kind === 'pdf' || kind === 'image') {
      const form = new FormData();
      form.append('file', file, file.name);
      form.append('instruction', instruction);
      const response = await fetch(`/api/document/giveme-suggestion-${kind}`, {
        method: 'POST',
        body: form,
        signal,
      });
      if (response.ok) {
        return { response, sourceName: file.name };
      }
      const fallBack = response.status === 422 || (kind === 'image' && response.status >= 500);
      if (!fallBack) {
        throw new Error(await extractFetchErrorMessage(response));
      }
    }
    const docx = await this.#toDocx(file, signal);
    const form = new FormData();
    form.append('file', docx, `${stemOf(file.name)}.docx`);
    form.append('instruction', instruction);
    const response = await postForm('/api/document/giveme-suggestion', form, signal);
    return { response, sourceName: docx.name };
  }

  // giveme-suggestion only reads .docx: PDFs and images are converted first, keeping their layout.
  async #toDocx(file: File, signal: AbortSignal): Promise<File> {
    const kind = attachmentKind(file);
    if (kind === null) {
      throw new Error(unsupportedAttachmentMessage(file));
    }
    if (kind === 'docx') {
      return file;
    }
    const form = new FormData();
    form.append('file', file, file.name);
    let path = '/api/document/image-to-words';
    if (kind === 'pdf') {
      path = '/api/document/extract-words';
      form.append('all_pages', 'true');
    }
    const response = await postForm(path, form, signal);
    if (response.status === 204) {
      throw new Error('No text or images found in this PDF');
    }
    const name = fileNameOf(
      response.headers.get('content-disposition') ?? undefined,
      `${stemOf(file.name)}.docx`,
    );
    const type = response.headers.get('content-type') ?? '';
    return new File([await response.blob()], name, { type });
  }

  #emitPart(
    subscriber: Subscriber<DocumentSuggestionEvent>,
    part: MultipartPart,
    index: number,
    sourceName: string,
  ): void {
    if (index === 0) {
      const type = part.headers['content-type'] ?? '';
      subscriber.next({
        type: 'file',
        fileName: fileNameOf(part.headers['content-disposition'], `suggested-${sourceName}`),
        blob: new Blob([part.body as BlobPart], { type }),
      });
      return;
    }
    const payload = JSON.parse(decoder.decode(part.body)) as SummaryPayload;
    const highlights = payload.highlights ?? [];
    if (typeof payload.summary === 'string') {
      subscriber.next({ type: 'summary', summary: payload.summary, highlights });
    } else {
      subscriber.next({
        type: 'summary-error',
        message: payload.error ?? 'Summary unavailable',
        highlights,
      });
    }
  }
}
