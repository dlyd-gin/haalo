import { Language } from '../language/language';
import { ConversationTurn, SplitId } from './conversation-turn';

export function createRecordingTurn(
  id: string,
  createdAt: number,
  originSplit: SplitId,
  language: Language,
): ConversationTurn {
  return { id, originSplit, language, createdAt, status: 'recording' };
}

export function addRecordingTurn(
  turns: readonly ConversationTurn[],
  newTurn: ConversationTurn,
): ConversationTurn[] {
  return [...turns, newTurn];
}

export function createReplyTurn(
  id: string,
  createdAt: number,
  sourceText: string,
  language: Language,
): ConversationTurn {
  return {
    id,
    createdAt,
    language,
    originSplit: 'native-speaker',
    status: 'processing',
    sourceText,
  };
}

export function addReplyTurn(
  turns: readonly ConversationTurn[],
  newTurn: ConversationTurn,
): ConversationTurn[] {
  return [...turns, newTurn];
}

export function markTurnProcessing(
  turns: readonly ConversationTurn[],
  id: string,
): ConversationTurn[] {
  return turns.map((turn) => (turn.id === id ? { ...turn, status: 'processing' as const } : turn));
}

export function markTurnStreaming(
  turns: readonly ConversationTurn[],
  id: string,
): ConversationTurn[] {
  return turns.map((turn) =>
    turn.id === id ? { ...turn, status: 'streaming' as const, translatedText: '' } : turn,
  );
}

export function markSttSourceStreaming(
  turns: readonly ConversationTurn[],
  id: string,
): ConversationTurn[] {
  return turns.map((turn) =>
    turn.id === id ? { ...turn, status: 'streaming' as const, sourceText: '' } : turn,
  );
}

export function appendSttSourceDelta(
  turns: readonly ConversationTurn[],
  id: string,
  delta: string,
): ConversationTurn[] {
  return turns.map((turn) =>
    turn.id === id ? { ...turn, sourceText: (turn.sourceText ?? '') + delta } : turn,
  );
}

export function appendTranslationDelta(
  turns: readonly ConversationTurn[],
  id: string,
  delta: string,
): ConversationTurn[] {
  return turns.map((turn) =>
    turn.id === id ? { ...turn, translatedText: (turn.translatedText ?? '') + delta } : turn,
  );
}

export function completeTtsTurn(
  turns: readonly ConversationTurn[],
  id: string,
): ConversationTurn[] {
  return turns.map((turn) => (turn.id === id ? { ...turn, status: 'ready' as const } : turn));
}

export function markTurnError(
  turns: readonly ConversationTurn[],
  id: string,
  errorMessage: string,
): ConversationTurn[] {
  return turns.map((turn) =>
    turn.id === id ? { ...turn, status: 'error' as const, errorMessage } : turn,
  );
}

export function resetConversation(): ConversationTurn[] {
  return [];
}
