import { DEFAULT_LANGUAGE } from '../language/language-catalog';
import { ConversationTurn } from './conversation-turn';
import {
  addRecordingTurn,
  addReplyTurn,
  appendSttSourceDelta,
  appendTranslationDelta,
  completeTtsTurn,
  createRecordingTurn,
  createReplyTurn,
  markSttSourceStreaming,
  markTurnError,
  markTurnProcessing,
  markTurnStreaming,
  resetConversation,
} from './conversation-turn.rules';

describe('conversation-turn.rules', () => {
  it('createRecordingTurn builds a recording turn for the given split and language', () => {
    const turn = createRecordingTurn('t1', 1000, 'foreign-speaker', DEFAULT_LANGUAGE);

    expect(turn).toEqual({
      id: 't1',
      originSplit: 'foreign-speaker',
      language: DEFAULT_LANGUAGE,
      createdAt: 1000,
      status: 'recording',
    });
  });

  it('addRecordingTurn appends without mutating the input array', () => {
    const existing: ConversationTurn[] = [];
    const turn = createRecordingTurn('t1', 1000, 'foreign-speaker', DEFAULT_LANGUAGE);

    const result = addRecordingTurn(existing, turn);

    expect(result).toEqual([turn]);
    expect(existing).toEqual([]);
  });

  it('createReplyTurn builds a processing native-speaker turn carrying the typed text', () => {
    const turn = createReplyTurn('t2', 2000, 'Where is the station?', DEFAULT_LANGUAGE);

    expect(turn).toEqual({
      id: 't2',
      originSplit: 'native-speaker',
      language: DEFAULT_LANGUAGE,
      createdAt: 2000,
      status: 'processing',
      sourceText: 'Where is the station?',
    });
  });

  it('addReplyTurn appends without mutating the input array', () => {
    const existing: ConversationTurn[] = [];
    const turn = createReplyTurn('t2', 2000, 'Where is the station?', DEFAULT_LANGUAGE);

    const result = addReplyTurn(existing, turn);

    expect(result).toEqual([turn]);
    expect(existing).toEqual([]);
  });

  it('markTurnProcessing flips only the matching turn to processing', () => {
    const turns: ConversationTurn[] = [
      createRecordingTurn('t1', 1000, 'foreign-speaker', DEFAULT_LANGUAGE),
      createRecordingTurn('t2', 1100, 'foreign-speaker', DEFAULT_LANGUAGE),
    ];

    const result = markTurnProcessing(turns, 't1');

    expect(result[0].status).toBe('processing');
    expect(result[1].status).toBe('recording');
    expect(turns[0].status).toBe('recording');
  });

  it('markSttSourceStreaming flips only the matching turn to streaming with empty sourceText', () => {
    const turns: ConversationTurn[] = [
      markTurnProcessing(
        [createRecordingTurn('t1', 1000, 'foreign-speaker', DEFAULT_LANGUAGE)],
        't1',
      )[0],
    ];

    const result = markSttSourceStreaming(turns, 't1');

    expect(result[0]).toEqual({ ...turns[0], status: 'streaming', sourceText: '' });
    expect(turns[0].status).toBe('processing');
  });

  it('appendSttSourceDelta appends to the matching turn without mutating the input array', () => {
    const streaming = markSttSourceStreaming(
      [createRecordingTurn('t1', 1000, 'foreign-speaker', DEFAULT_LANGUAGE)],
      't1',
    );

    const afterFirst = appendSttSourceDelta(streaming, 't1', 'こんに');
    const afterSecond = appendSttSourceDelta(afterFirst, 't1', 'ちは');

    expect(afterSecond[0].sourceText).toBe('こんにちは');
    expect(afterFirst[0].sourceText).toBe('こんに');
    expect(streaming[0].sourceText).toBe('');
  });

  it('markTurnStreaming flips only the matching turn to streaming with empty translatedText', () => {
    const turns: ConversationTurn[] = [
      createReplyTurn('t2', 2000, 'Where is the station?', DEFAULT_LANGUAGE),
      createReplyTurn('t3', 2100, 'Thank you', DEFAULT_LANGUAGE),
    ];

    const result = markTurnStreaming(turns, 't2');

    expect(result[0]).toEqual({ ...turns[0], status: 'streaming', translatedText: '' });
    expect(result[1]).toEqual(turns[1]);
    expect(turns[0].status).toBe('processing');
  });

  it('appendTranslationDelta appends to the matching turn without mutating the input array', () => {
    const streaming = markTurnStreaming(
      [createReplyTurn('t2', 2000, 'Where is the station?', DEFAULT_LANGUAGE)],
      't2',
    );

    const afterFirst = appendTranslationDelta(streaming, 't2', '駅は');
    const afterSecond = appendTranslationDelta(afterFirst, 't2', 'どこですか');

    expect(afterSecond[0].translatedText).toBe('駅はどこですか');
    expect(afterFirst[0].translatedText).toBe('駅は');
    expect(streaming[0].translatedText).toBe('');
  });

  it('completeTtsTurn flips only the matching turn to ready', () => {
    const turns: ConversationTurn[] = [
      createReplyTurn('t2', 2000, 'Hello', DEFAULT_LANGUAGE),
      createReplyTurn('t3', 2100, 'Thanks', DEFAULT_LANGUAGE),
    ];

    const result = completeTtsTurn(turns, 't2');

    expect(result[0]).toEqual({ ...turns[0], status: 'ready' });
    expect(result[1]).toEqual(turns[1]);
    expect(turns[0].status).toBe('processing');
  });

  it('markTurnError resolves the matching turn to error with a message', () => {
    const turns: ConversationTurn[] = [
      createRecordingTurn('t1', 1000, 'foreign-speaker', DEFAULT_LANGUAGE),
    ];

    const result = markTurnError(turns, 't1', 'Microphone permission denied');

    expect(result[0]).toEqual({
      ...turns[0],
      status: 'error',
      errorMessage: 'Microphone permission denied',
    });
  });

  it('resetConversation returns an empty array', () => {
    expect(resetConversation()).toEqual([]);
  });
});
