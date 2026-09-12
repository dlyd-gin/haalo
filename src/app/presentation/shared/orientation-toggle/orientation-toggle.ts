import { Component, inject } from '@angular/core';
import { LayoutPreferencesStore } from '../../layout/layout-preferences';
import { Icon } from '../icon/icon';

@Component({
  selector: 'orientation-toggle',
  imports: [Icon],
  templateUrl: './orientation-toggle.html',
  styleUrl: './orientation-toggle.scss',
})
export class OrientationToggle {
  protected readonly layout = inject(LayoutPreferencesStore);
}
