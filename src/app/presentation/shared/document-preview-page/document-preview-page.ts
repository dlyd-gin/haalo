import {
  Component,
  ElementRef,
  afterRenderEffect,
  computed,
  effect,
  inject,
  input,
  linkedSignal,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { ConversationStore, PreviewSource } from '../../../application/conversation-store';
import { AttachmentKind } from '../../../domain/conversation/conversation-turn';
import { attachmentKind } from '../../../infrastructure/document/document.port';
import { Icon } from '../icon/icon';

interface PreviewItem {
  readonly turnId: string;
  readonly fileName: string;
  readonly kind: AttachmentKind;
  readonly blob: Blob | undefined;
}

@Component({
  selector: 'document-preview-page',
  imports: [Icon],
  templateUrl: './document-preview-page.html',
  styleUrl: './document-preview-page.scss',
  host: {
    '(document:keydown.escape)': 'onEscape()',
  },
})
export class DocumentPreviewPage {
  #store = inject(ConversationStore);
  #sanitizer = inject(DomSanitizer);

  // null = closed. The page stays mounted while closed so its slide-out can play, so the list
  // keeps showing the last source instead of emptying mid-animation.
  readonly source = input<PreviewSource | null>(null);
  readonly closed = output<void>();

  protected readonly shownSource = linkedSignal<PreviewSource | null, PreviewSource>({
    source: this.source,
    computation: (source, previous) => source ?? previous?.value ?? 'attachment',
  });

  protected readonly title = computed(() =>
    this.shownSource() === 'attachment' ? 'Attachments' : 'Suggested documents',
  );

  protected readonly items = computed<readonly PreviewItem[]>(() => {
    const turns = this.#store.turns();
    if (this.shownSource() === 'attachment') {
      return turns
        .filter((turn) => turn.attachment)
        .map((turn) => ({
          turnId: turn.id,
          fileName: turn.attachment!.fileName,
          kind: turn.attachment!.kind,
          blob: this.#store.attachmentFile(turn.id),
        }));
    }
    return turns
      .filter((turn) => turn.suggestion?.fileName)
      .map((turn) => {
        const fileName = turn.suggestion!.fileName!;
        const blob = this.#store.suggestionFile(turn.id);
        // A highlighted PDF (giveme-suggestion-pdf) or a highlighted docx (the conversion path).
        const kind = attachmentKind({ name: fileName, type: blob?.type ?? '' }) ?? 'docx';
        return { turnId: turn.id, fileName, kind, blob };
      });
  });

  // No default selection — reset every time the page opens, closes or switches list.
  protected readonly selectedId = linkedSignal<PreviewSource | null, string | null>({
    source: this.source,
    computation: () => null,
  });
  // Equal while it's the same document, so unrelated turn updates (e.g. a streaming translation)
  // don't recreate the object URL or re-render the docx.
  protected readonly selected = computed(
    () => this.items().find((item) => item.turnId === this.selectedId()) ?? null,
    { equal: (a, b) => a?.turnId === b?.turnId && a?.blob === b?.blob },
  );

  protected readonly objectUrl = signal<string | null>(null);
  protected readonly frameUrl = computed<SafeResourceUrl | null>(() => {
    const url = this.objectUrl();
    return url && this.selected()?.kind === 'pdf'
      ? this.#sanitizer.bypassSecurityTrustResourceUrl(url)
      : null;
  });
  protected readonly docxStatus = signal<'loading' | 'ready' | 'error'>('loading');

  protected readonly pageHost = viewChild.required<ElementRef<HTMLElement>>('pageHost');
  protected readonly closeButton = viewChild.required<ElementRef<HTMLButtonElement>>('closeButton');

  #returnFocusTo: HTMLElement | null = null;

  constructor() {
    // One object URL per selection: revoked when the selection changes and on destroy.
    effect((onCleanup) => {
      const item = this.selected();
      if (!item?.blob) {
        this.objectUrl.set(null);
        return;
      }
      const url = URL.createObjectURL(item.blob);
      this.objectUrl.set(url);
      onCleanup(() => URL.revokeObjectURL(url));
    });

    // Runs after the DOM has updated, so pageHost is cleared and visible before docx-preview
    // renders into it. Browser-only: docx-preview needs the DOM, so it's imported lazily (which
    // also keeps it out of the SSR bundle).
    afterRenderEffect((onCleanup) => {
      const item = this.selected();
      const host = this.pageHost().nativeElement;
      host.replaceChildren();
      if (item?.kind !== 'docx' || !item.blob) {
        return;
      }
      let isCurrent = true;
      onCleanup(() => (isCurrent = false));
      untracked(() => this.docxStatus.set('loading'));
      import('docx-preview')
        .then(({ renderAsync }) =>
          renderAsync(item.blob!, host, undefined, {
            className: 'docx-page',
            inWrapper: true,
            breakPages: true,
          }),
        )
        .then(() => isCurrent && this.docxStatus.set('ready'))
        .catch((error: unknown) => {
          console.error('[DocumentPreviewPage] render failed', error);
          if (isCurrent) {
            this.docxStatus.set('error');
          }
        });
    });

    // Focus follows the slide: into the page on open, back to whatever opened it on close.
    let wasOpen = false;
    afterRenderEffect(() => {
      const isOpen = this.source() !== null;
      if (isOpen === wasOpen) {
        return;
      }
      wasOpen = isOpen;
      if (isOpen) {
        this.#returnFocusTo = document.activeElement as HTMLElement | null;
        this.closeButton().nativeElement.focus({ preventScroll: true });
      } else {
        this.#returnFocusTo?.focus({ preventScroll: true });
        this.#returnFocusTo = null;
      }
    });
  }

  select(turnId: string): void {
    this.selectedId.set(turnId);
  }

  onEscape(): void {
    if (this.source() !== null) {
      this.closed.emit();
    }
  }
}
