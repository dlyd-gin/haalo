import { Language } from '../language/language';

export type SplitId = 'foreign-speaker' | 'native-speaker';
export type TurnStatus = 'recording' | 'processing' | 'streaming' | 'ready' | 'error';
export type AttachmentKind = 'pdf' | 'image' | 'docx';

export interface TurnAttachment {
  readonly fileName: string;
  readonly kind: AttachmentKind;
}

/** document-service's giveme-suggestion result; the highlighted document itself lives in the store. */
export interface TurnSuggestion {
  readonly fileName?: string; // set once the highlighted document has arrived (preview available)
  readonly summary?: string;
  readonly highlights?: readonly string[];
  readonly summaryError?: string;
}

/**
 * foreign-speaker turns: sourceText = recognized Japanese (or other foreign language), translatedText = English rendering.
 * native-speaker turns: sourceText = typed English, translatedText = foreign-language rendering used for TTS.
 * native-speaker attachment turns: sourceText = the instruction; never translated, only shown on the native side.
 */
export interface ConversationTurn {
  readonly id: string;
  readonly originSplit: SplitId;
  readonly status: TurnStatus;
  readonly createdAt: number;
  readonly language: Language;
  readonly sourceText?: string;
  readonly translatedText?: string;
  readonly errorMessage?: string;
  readonly attachment?: TurnAttachment;
  readonly suggestion?: TurnSuggestion;
}
