import { Component, input, output } from '@angular/core';
import { Icon } from '../icon/icon';

@Component({
  selector: 'mic-button',
  imports: [Icon],
  templateUrl: './mic-button.html',
  styleUrl: './mic-button.scss',
})
export class MicButton {
  readonly isRecording = input(false);
  readonly isProcessing = input(false);
  readonly iconSize = input<'sm' | 'md' | 'lg'>('md');
  readonly size = input<'md' | 'sm'>('md');

  readonly pressStart = output<void>();
  readonly pressEnd = output<void>();
  readonly pressCancel = output<void>();

  #spaceHeld = false;

  onPointerDown(event: PointerEvent): void {
    if (this.isProcessing() || this.isRecording()) {
      return;
    }
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    this.pressStart.emit();
  }

  onPointerUp(): void {
    if (!this.isRecording()) {
      return;
    }
    this.pressEnd.emit();
  }

  onPointerCancel(): void {
    if (!this.isRecording()) {
      return;
    }
    this.pressCancel.emit();
  }

  onKeyDown(event: KeyboardEvent): void {
    if (event.code !== 'Space') {
      return;
    }
    if (event.repeat || this.#spaceHeld || this.isProcessing() || this.isRecording()) {
      return;
    }
    event.preventDefault();
    this.#spaceHeld = true;
    this.pressStart.emit();
  }

  onKeyUp(event: KeyboardEvent): void {
    if (event.code !== 'Space' || !this.#spaceHeld) {
      return;
    }
    event.preventDefault();
    this.#spaceHeld = false;
    this.pressEnd.emit();
  }
}
