import { useEffect, type RefObject } from 'react';

import { SPACE } from '../density';

// Every bar shown now, and the page's own value from before the first one: bars may mount and
// unmount in any order (a form's footer and a settings save bar), so the padding is the tallest
// one's and the page's value comes back only when the last goes (lane A's #402 review).
const shownBars = new Set<HTMLElement>();
let pageValue: string | null = null;

function apply(): void {
  const root = document.documentElement;
  if (shownBars.size === 0) {
    if (pageValue !== null) root.style.scrollPaddingBottom = pageValue;
    pageValue = null;
    return;
  }
  const tallest = Math.max(...[...shownBars].map((bar) => bar.offsetHeight));
  root.style.scrollPaddingBottom = `${String(tallest + SPACE.md)}px`;
}

/**
 * Keep a bar stuck to the window's foot from hiding the field that has focus (WCAG 2.4.11,
 * QA V-01): while the bar is shown, the window keeps its height clear when it scrolls a
 * focused field into view. The page's own value comes back when the last bar goes.
 */
export function useClearOfBar(bar: RefObject<HTMLElement | null>, shown = true): void {
  useEffect(() => {
    const node = bar.current;
    if (!shown || node === null || typeof ResizeObserver === 'undefined') return undefined;
    if (shownBars.size === 0) pageValue = document.documentElement.style.scrollPaddingBottom;
    shownBars.add(node);
    apply();
    const watch = new ResizeObserver(apply);
    watch.observe(node);
    return () => {
      watch.disconnect();
      shownBars.delete(node);
      apply();
    };
  }, [bar, shown]);
}
