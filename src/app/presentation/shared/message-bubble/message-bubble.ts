import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
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
  readonly previewAttachment = output<string>();
  readonly previewSuggestion = output<string>();

  #destroyRef = inject(DestroyRef);

  // Attachment turns show their error as a ! icon whose message is a click-to-toggle tooltip.
  protected readonly isErrorTipOpen = signal(false);
  protected readonly errorAnchor = viewChild<ElementRef<HTMLElement>>('errorAnchor');

  // Own messages ('end'): lead with what was actually said/typed (sourceText).
  // Counterpart messages ('start'): lead with the translation, since that's what's readable here.
  readonly primaryText = computed(() =>
    this.align() === 'end' ? this.turn().sourceText : this.turn().translatedText,
  );
  // Own messages need no translation caption — the speaker already knows what they said.
  readonly secondaryText = computed(() =>
    this.align() === 'end' ? undefined : this.turn().sourceText,
  );

  constructor() {
    // Same zoneless global-listener idiom as native-speaker's composer: close the tooltip on an
    // outside press or Escape.
    afterNextRender(() => {
      const onDocumentPointerDown = (event: PointerEvent) => {
        if (!this.isErrorTipOpen()) {
          return;
        }
        const anchor = this.errorAnchor()?.nativeElement;
        if (!anchor || !anchor.contains(event.target as Node)) {
          this.isErrorTipOpen.set(false);
        }
      };
      const onDocumentKeydown = (event: KeyboardEvent) => {
        if (event.key === 'Escape' && this.isErrorTipOpen()) {
          this.isErrorTipOpen.set(false);
        }
      };

      document.addEventListener('pointerdown', onDocumentPointerDown, { capture: true });
      document.addEventListener('keydown', onDocumentKeydown);

      this.#destroyRef.onDestroy(() => {
        document.removeEventListener('pointerdown', onDocumentPointerDown, { capture: true });
        document.removeEventListener('keydown', onDocumentKeydown);
      });
    });
  }

  onAttachmentClick(): void {
    this.previewAttachment.emit(this.turn().id);
  }

  onPreviewClick(): void {
    if (this.turn().suggestion?.fileName) {
      this.previewSuggestion.emit(this.turn().id);
    }
  }

  toggleErrorTip(): void {
    this.isErrorTipOpen.update((open) => !open);
  }

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
