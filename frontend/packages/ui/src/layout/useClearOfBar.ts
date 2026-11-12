import { useEffect, type RefObject } from 'react';

import { SPACE } from '../density';

/**
 * Keep a bar stuck to the window's foot from hiding the field that has focus (WCAG 2.4.11,
 * QA V-01): while the bar is shown, the window keeps its height clear when it scrolls a
 * focused field into view. The page's own value comes back when the bar goes.
 */
export function useClearOfBar(bar: RefObject<HTMLElement | null>, shown = true): void {
  useEffect(() => {
    const node = bar.current;
    const root = document.documentElement;
    if (!shown || node === null || typeof ResizeObserver === 'undefined') return undefined;
    const before = root.style.scrollPaddingBottom;
    const fit = () => {
      root.style.scrollPaddingBottom = `${String(node.offsetHeight + SPACE.md)}px`;
    };
    fit();
    const watch = new ResizeObserver(fit);
    watch.observe(node);
    return () => {
      watch.disconnect();
      root.style.scrollPaddingBottom = before;
    };
  }, [bar, shown]);
}
