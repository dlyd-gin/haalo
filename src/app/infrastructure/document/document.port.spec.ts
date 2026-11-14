import { attachmentKind, unsupportedAttachmentMessage } from './document.port';

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

describe('attachmentKind', () => {
  it('routes by MIME type, falling back to the extension', () => {
    expect(attachmentKind({ name: 'menu.pdf', type: 'application/pdf' })).toBe('pdf');
    expect(attachmentKind({ name: 'MENU.PDF', type: '' })).toBe('pdf');
    expect(attachmentKind({ name: 'photo.heic', type: 'image/heic' })).toBe('image');
    expect(attachmentKind({ name: 'menu.docx', type: DOCX_MIME })).toBe('docx');
    expect(attachmentKind({ name: 'menu.docx', type: '' })).toBe('docx');
  });

  it('rejects legacy .doc and other files', () => {
    const doc = { name: 'menu.doc', type: 'application/msword' };
    expect(attachmentKind(doc)).toBeNull();
    expect(unsupportedAttachmentMessage(doc)).toBe('Only .docx Word files are supported');

    const text = { name: 'notes.txt', type: 'text/plain' };
    expect(attachmentKind(text)).toBeNull();
    expect(unsupportedAttachmentMessage(text)).toBe('Attach a PDF, an image or a .docx file');
  });
});
