import { Component, computed, input, output } from '@angular/core';
import { ConversationTurn } from '../../../domain/conversation/conversation-turn';
import { Icon } from '../icon/icon';

@Component({
  selector: 'message-bubble',
  imports: [Icon],
  templateUrl: './message-bubble.html',
  styleUrl: './message-bubble.scss',
})
export class MessageBubble {
  readonly turn = input.required<ConversationTurn>();
  // 'end' = this turn originated on the panel viewing it (the reader's own message).
  readonly align = input<'start' | 'end'>('start');
  readonly showPlayButton = input(false);
  // Driven by the store's real playback state (ConversationStore.playingTurnId),
  // not local guesswork — so the icon reverts on its own when a clip actually
  // finishes, errors, or is paused elsewhere.
  readonly isPlaying = input(false);

  readonly play = output<string>();
  readonly pause = output<string>();

  // Own messages ('end'): lead with what was actually said/typed (sourceText).
  // Counterpart messages ('start'): lead with the translation, since that's what's readable here.
  readonly primaryText = computed(() =>
    this.align() === 'end' ? this.turn().sourceText : this.turn().translatedText,
  );
  // Own messages need no translation caption — the speaker already knows what they said.
  readonly secondaryText = computed(() =>
    this.align() === 'end' ? undefined : this.turn().sourceText,
  );

  onPlayClick(): void {
    if (this.turn().status !== 'ready') {
      return;
    }
    if (this.isPlaying()) {
      this.pause.emit(this.turn().id);
    } else {
      this.play.emit(this.turn().id);
    }
  }
}
