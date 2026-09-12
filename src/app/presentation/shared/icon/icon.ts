import { Component, input } from '@angular/core';

export type IconName =
  | 'mic'
  | 'menu'
  | 'orientation-stack'
  | 'orientation-side'
  | 'play'
  | 'sound-wave-progress'
  | 'sound-wave-play'
  | 'error'
  | 'send'
  | 'reset'
  | 'compose';

@Component({
  selector: 'svg-icon',
  templateUrl: './icon.html',
  styleUrl: './icon.scss',
})
export class Icon {
  readonly name = input.required<IconName>();
  readonly filled = input(false);
  readonly size = input<'sm' | 'md' | 'lg'>('md');
}
