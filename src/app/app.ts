import { Component, inject } from '@angular/core';
import { AppHeader } from './presentation/shared/app-header/app-header';
import { ForeignSpeaker } from './presentation/features/foreign-speaker/foreign-speaker';
import { NativeSpeaker } from './presentation/features/native-speaker/native-speaker';
import { ConversationStore } from './application/conversation-store';
import { DocumentPreviewPage } from './presentation/shared/document-preview-page/document-preview-page';
import { LayoutPreferencesStore } from './presentation/layout/layout-preferences';

@Component({
  selector: 'app-root',
  imports: [AppHeader, ForeignSpeaker, NativeSpeaker, DocumentPreviewPage],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly layout = inject(LayoutPreferencesStore);
  protected readonly store = inject(ConversationStore);
}
