import { Component, inject, signal } from '@angular/core';
import { ConversationStore } from '../../../application/conversation-store';
import { LanguagePicker } from '../language-picker/language-picker';
import { OrientationToggle } from '../orientation-toggle/orientation-toggle';
import { Icon } from '../icon/icon';

@Component({
  selector: 'app-header',
  imports: [LanguagePicker, OrientationToggle, Icon],
  templateUrl: './app-header.html',
  styleUrl: './app-header.scss',
})
export class AppHeader {
  protected readonly store = inject(ConversationStore);
  protected readonly menuOpen = signal(false);

  toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }

  closeMenu(): void {
    this.menuOpen.set(false);
  }
}
