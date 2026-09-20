import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ConversationStore } from '../../../application/conversation-store';
import { MessageBubble } from '../../shared/message-bubble/message-bubble';
import { Icon } from '../../shared/icon/icon';
import { MicButton } from '../../shared/mic-button/mic-button';

@Component({
  selector: 'native-speaker',
  imports: [MessageBubble, Icon, MicButton],
  templateUrl: './native-speaker.html',
  styleUrl: './native-speaker.scss',
})
export class NativeSpeaker {
  protected readonly store = inject(ConversationStore);
  #destroyRef = inject(DestroyRef);

  protected readonly draftText = signal('');
  protected readonly canSend = computed(
    () => this.draftText().trim().length > 0 && !this.store.isSending(),
  );

  protected readonly isExpanded = signal(false);

  // Component-local — no turn exists for this flow to derive it from, unlike
  // foreign-speaker's isProcessing, which is computed off turn status.
  protected readonly isNativeProcessing = signal(false);

  protected readonly composerRoot = viewChild<ElementRef<HTMLElement>>('composerRoot');
  protected readonly textareaEl = viewChild<ElementRef<HTMLTextAreaElement>>('textareaEl');
  protected readonly fabButton = viewChild<ElementRef<HTMLButtonElement>>('fabButton');

  constructor() {
    // Zoneless-safe global listeners, mirroring LayoutPreferencesStore's
    // afterNextRender + DestroyRef.onDestroy idiom (document doesn't exist at
    // prerender time, and cleanup must run once, on component destroy).
    afterNextRender(() => {
      const onDocumentPointerDown = (event: PointerEvent) => {
        if (!this.isExpanded()) {
          return;
        }
        const root = this.composerRoot()?.nativeElement;
        if (root && !root.contains(event.target as Node)) {
          this.collapse();
        }
      };
      const onDocumentKeydown = (event: KeyboardEvent) => {
        if (event.key === 'Escape' && this.isExpanded()) {
          this.collapse();
        }
      };

      document.addEventListener('pointerdown', onDocumentPointerDown, { capture: true });
      document.addEventListener('keydown', onDocumentKeydown);

      this.#destroyRef.onDestroy(() => {
        document.removeEventListener('pointerdown', onDocumentPointerDown, { capture: true });
        document.removeEventListener('keydown', onDocumentKeydown);
      });
    });

    // Focus management: move focus explicitly whenever isExpanded flips — no
    // ambient change detection to rely on in zoneless mode. Skip the effect's
    // first run so page load doesn't steal focus onto the idle FAB.
    let isFirstRun = true;
    effect(() => {
      const expanded = this.isExpanded();
      if (isFirstRun) {
        isFirstRun = false;
        return;
      }
      if (expanded) {
        this.textareaEl()?.nativeElement.focus();
      } else {
        this.fabButton()?.nativeElement.focus();
      }
    });
  }

  expand(): void {
    this.isExpanded.set(true);
  }

  collapse(): void {
    this.isExpanded.set(false);
  }

  onInput(value: string): void {
    this.draftText.set(value);
  }

  onSend(): void {
    if (!this.canSend()) {
      return;
    }
    this.store.sendReply(this.draftText());
    this.draftText.set('');
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.onSend();
    }
  }

  onMicPressStart(): void {
    this.store.startNativeCapture();
  }

  onMicPressEnd(): void {
    this.isNativeProcessing.set(true);
    this.store.stopNativeCapture().subscribe({
      next: (event) => {
        if (event.type === 'source-done') {
          this.draftText.set(event.sourceText);
        } else if (event.type === 'error') {
          console.error('[NativeSpeaker] native capture failed', event.message);
        }
      },
      complete: () => this.isNativeProcessing.set(false),
      error: () => this.isNativeProcessing.set(false),
    });
  }

  onMicPressCancel(): void {
    this.onMicPressEnd();
  }
}
