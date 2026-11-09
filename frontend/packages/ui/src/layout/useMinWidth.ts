import { useSyncExternalStore } from 'react';

/**
 * Whether the window is at least `px` wide, kept live as it resizes (D-147 templates: a list may
 * show a default column only where it fits). False where there is no window or no matchMedia.
 */
export function useMinWidth(px: number): boolean {
  const query = `(min-width: ${String(px)}px)`;
  return useSyncExternalStore(
    (changed) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
        return () => undefined;
      }
      const media = window.matchMedia(query);
      media.addEventListener('change', changed);
      return () => {
        media.removeEventListener('change', changed);
      };
    },
    () =>
      typeof window !== 'undefined' && typeof window.matchMedia === 'function'
        ? window.matchMedia(query).matches
        : false,
    () => false,
  );
}
