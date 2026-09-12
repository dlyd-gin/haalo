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
  viewChildren,
} from '@angular/core';
import { ConversationStore } from '../../../application/conversation-store';
import { Language } from '../../../domain/language/language';
import { SUPPORTED_LANGUAGES } from '../../../domain/language/language-catalog';
import { orderLanguagesBySelected } from '../../../domain/language/language.rules';

@Component({
  selector: 'language-picker',
  templateUrl: './language-picker.html',
  styleUrl: './language-picker.scss',
})
export class LanguagePicker {
  protected readonly store = inject(ConversationStore);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly languages = SUPPORTED_LANGUAGES;
  protected readonly orderedLanguages = computed(() =>
    orderLanguagesBySelected(this.languages, this.store.foreignLanguage().code),
  );

  protected readonly isExpanded = signal(false);

  protected readonly pickerRoot = viewChild<ElementRef<HTMLElement>>('pickerRoot');
  protected readonly triggerButton = viewChild<ElementRef<HTMLButtonElement>>('triggerButton');
  protected readonly optionButtons = viewChildren<ElementRef<HTMLButtonElement>>('optionButton');

  constructor() {
    // Zoneless-safe global listeners, mirroring native-speaker's composer
    // afterNextRender + DestroyRef.onDestroy idiom (document doesn't exist at
    // prerender time, and cleanup must run once, on component destroy).
    afterNextRender(() => {
      const onDocumentPointerDown = (event: PointerEvent) => {
        if (!this.isExpanded()) {
          return;
        }
        const root = this.pickerRoot()?.nativeElement;
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

      this.destroyRef.onDestroy(() => {
        document.removeEventListener('pointerdown', onDocumentPointerDown, { capture: true });
        document.removeEventListener('keydown', onDocumentKeydown);
      });
    });

    // Focus management: move focus explicitly whenever isExpanded flips — no
    // ambient change detection to rely on in zoneless mode. Mirrors native-speaker's
    // fabButton/textareaEl swap: trigger and options are never simultaneously
    // in the DOM, so the ref for the side we're leaving is still valid here.
    let isFirstRun = true;
    effect(() => {
      const expanded = this.isExpanded();
      if (isFirstRun) {
        isFirstRun = false;
        return;
      }
      if (expanded) {
        this.optionButtons()[0]?.nativeElement.focus();
      } else {
        this.triggerButton()?.nativeElement.focus();
      }
    });
  }

  expand(): void {
    this.isExpanded.set(true);
  }

  collapse(): void {
    this.isExpanded.set(false);
  }

  select(language: Language): void {
    this.store.setForeignLanguage(language);
    this.collapse();
  }
}
