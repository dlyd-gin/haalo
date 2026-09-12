import { Language } from '../language/language';

export type SplitId = 'foreign-speaker' | 'native-speaker';
export type TurnStatus = 'recording' | 'processing' | 'streaming' | 'ready' | 'error';

/**
 * foreign-speaker turns: sourceText = recognized Japanese (or other foreign language), translatedText = English rendering.
 * native-speaker turns: sourceText = typed English, translatedText = foreign-language rendering used for TTS.
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
}
