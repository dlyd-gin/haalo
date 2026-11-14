import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';
import { AttachmentKind } from '../../domain/conversation/conversation-turn';

// In stream order: the highlighted document (PDF or docx) arrives first, then its summary (or why there is none).
export type DocumentSuggestionEvent =
  | { readonly type: 'file'; readonly fileName: string; readonly blob: Blob }
  | { readonly type: 'summary'; readonly summary: string; readonly highlights: readonly string[] }
  | {
      readonly type: 'summary-error';
      readonly message: string;
      readonly highlights: readonly string[];
    };

export interface DocumentPort {
  suggest(file: File, instruction: string): Observable<DocumentSuggestionEvent>;
}

export const DOCUMENT_PORT = new InjectionToken<DocumentPort>('DOCUMENT_PORT');

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

function extensionOf(fileName: string): string {
  const dot = fileName.lastIndexOf('.');
  return dot === -1 ? '' : fileName.slice(dot + 1).toLowerCase();
}

export function attachmentKind(file: Pick<File, 'name' | 'type'>): AttachmentKind | null {
  const extension = extensionOf(file.name);
  if (file.type === 'application/pdf' || extension === 'pdf') {
    return 'pdf';
  }
  if (file.type === DOCX_MIME || extension === 'docx') {
    return 'docx';
  }
  if (file.type.startsWith('image/')) {
    return 'image';
  }
  return null;
}

export function unsupportedAttachmentMessage(file: Pick<File, 'name' | 'type'>): string {
  // Legacy binary Word: document-service only reads the .docx (OOXML) format.
  if (file.type === 'application/msword' || extensionOf(file.name) === 'doc') {
    return 'Only .docx Word files are supported';
  }
  return 'Attach a PDF, an image or a .docx file';
}
