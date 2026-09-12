import { Component, computed, inject } from '@angular/core';
import { ConversationStore } from '../../../application/conversation-store';
import { MessageBubble } from '../../shared/message-bubble/message-bubble';
import { MicButton } from '../../shared/mic-button/mic-button';

@Component({
  selector: 'foreign-speaker',
  imports: [MicButton, MessageBubble],
  templateUrl: './foreign-speaker.html',
  styleUrl: './foreign-speaker.scss',
})
export class ForeignSpeaker {
  protected readonly store = inject(ConversationStore);

  protected readonly isProcessing = computed(() =>
    this.store
      .turns()
      .some((turn) => turn.originSplit === 'foreign-speaker' && turn.status === 'processing'),
  );

  onPressStart(): void {
    this.store.startRecording();
  }

  onPressEnd(): void {
    this.store.stopRecording();
  }

  onPressCancel(): void {
    this.store.stopRecording();
  }

  onPlay(turnId: string): void {
    this.store.playTurnAudio(turnId);
  }

  onPause(turnId: string): void {
    this.store.pauseTurnAudio(turnId);
  }
}
