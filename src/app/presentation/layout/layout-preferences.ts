import { DestroyRef, Injectable, afterNextRender, computed, inject, signal } from '@angular/core';

export type LayoutOrientation = 'horizontal' | 'vertical';

const BREAKPOINT_PX = 700;

export function resolveOrientationFromWidth(
  width: number,
  breakpointPx = BREAKPOINT_PX,
): LayoutOrientation {
  return width < breakpointPx ? 'vertical' : 'horizontal';
}

@Injectable({ providedIn: 'root' })
export class LayoutPreferencesStore {
  #destroyRef = inject(DestroyRef);

  // SSR-safe default: window.innerWidth is unknown at prerender time, so this only
  // ever gets a real measurement post-hydration, inside afterNextRender below.
  #viewportWidth = signal(BREAKPOINT_PX);

  // Only set once the user explicitly clicks the toggle (always post-hydration, so it
  // never contributes to an SSR/hydration flash). null means "defer to the plain CSS
  // @media breakpoint", which is what renders correctly on first paint with zero JS.
  #manualOverride = signal<LayoutOrientation | null>(null);
  readonly manualOverride = this.#manualOverride.asReadonly();

  readonly orientation = computed(
    () => this.#manualOverride() ?? resolveOrientationFromWidth(this.#viewportWidth()),
  );

  constructor() {
    afterNextRender(() => {
      this.#viewportWidth.set(window.innerWidth);

      const onResize = () => this.#viewportWidth.set(window.innerWidth);
      window.addEventListener('resize', onResize);
      this.#destroyRef.onDestroy(() => window.removeEventListener('resize', onResize));
    });
  }

  toggleOrientation(): void {
    const next: LayoutOrientation = this.orientation() === 'horizontal' ? 'vertical' : 'horizontal';
    console.log('[LayoutPreferencesStore] toggleOrientation ->', next);
    this.#manualOverride.set(next);
  }
}
