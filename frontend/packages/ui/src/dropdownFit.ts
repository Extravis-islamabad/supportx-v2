import { useEffect } from 'react';

/**
 * Dropdown lists grow to fit their options (product owner, 2026-10-28): at least as wide as
 * their field (Ant Design's own width), wider for the longest option shown, up to 360 px and
 * never past the screen. Ant Design's lists are virtual (their rows are positioned out of the
 * flow), so CSS cannot size them by content; this measures the options shown when a list opens
 * or changes and sets the list's `min-width`, which only ever widens it.
 */

export const LIST_MAX_WIDTH = 360;
const SCREEN_GUTTER = 16;
// The list's own padding and room for its scroll bar, beside each option's padding.
const LIST_CHROME = 8 + 10;

/** The list's minimum width for options of these natural (one-line) widths. */
export function fittedMinWidth(
  optionWidths: readonly number[],
  optionPadding: number,
  viewport: number,
): number {
  const widest = Math.max(0, ...optionWidths);
  if (widest === 0) return 0;
  const want = Math.ceil(widest + optionPadding + LIST_CHROME);
  return Math.min(want, LIST_MAX_WIDTH, viewport - SCREEN_GUTTER);
}

let canvas: HTMLCanvasElement | null = null;

// Measured with a canvas, so measuring never changes the page (and never re-triggers a fit).
function naturalWidth(content: HTMLElement): number {
  canvas ??= document.createElement('canvas');
  const context = canvas.getContext('2d');
  if (context === null) return content.scrollWidth;
  context.font = getComputedStyle(content).font;
  return context.measureText(content.textContent).width;
}

function fit(popup: HTMLElement): void {
  if (popup.classList.contains('ant-select-dropdown-hidden')) return;
  const contents = [...popup.querySelectorAll<HTMLElement>('.ant-select-item-option-content')];
  const option = contents[0]?.closest<HTMLElement>('.ant-select-item-option');
  // No layout (a test DOM, a list not shown yet): nothing to measure against.
  if (option === null || option === undefined || option.getBoundingClientRect().width === 0) {
    return;
  }
  const style = getComputedStyle(option);
  const padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  const width = fittedMinWidth(contents.map(naturalWidth), padding, window.innerWidth);
  const next = width > 0 ? `${String(width)}px` : '';
  if (popup.style.minWidth !== next) popup.style.minWidth = next;
}

function listOf(node: Node): HTMLElement | null {
  const element = node instanceof HTMLElement ? node : node.parentElement;
  return element?.closest<HTMLElement>('.ant-select-dropdown') ?? null;
}

/** Fits every Select list in the page while mounted (once, in the appearance provider). */
export function useDropdownFit(): void {
  useEffect(() => {
    if (typeof MutationObserver === 'undefined') return undefined;
    const watched = new WeakSet<HTMLElement>();
    const refit = (records: MutationRecord[]) => {
      const lists = new Set<HTMLElement>();
      for (const record of records) {
        const list = listOf(record.target);
        if (list !== null) lists.add(list);
      }
      lists.forEach(fit);
    };
    // The list itself opening or re-sized by Ant Design; inside it, only rows coming and going
    // (scrolling a virtual list, searching), never hover states.
    const opened = new MutationObserver(refit);
    const rows = new MutationObserver(refit);
    const watch = (list: HTMLElement) => {
      fit(list);
      if (watched.has(list)) return;
      watched.add(list);
      opened.observe(list, { attributes: true, attributeFilter: ['class', 'style'] });
      rows.observe(list, { childList: true, subtree: true });
    };
    const added = new MutationObserver((records) => {
      for (const record of records) {
        record.addedNodes.forEach((node) => {
          if (!(node instanceof HTMLElement)) return;
          if (node.classList.contains('ant-select-dropdown')) watch(node);
          node.querySelectorAll<HTMLElement>('.ant-select-dropdown').forEach(watch);
        });
      }
    });
    added.observe(document.body, { childList: true, subtree: true });
    document.querySelectorAll<HTMLElement>('.ant-select-dropdown').forEach(watch);
    return () => {
      added.disconnect();
      opened.disconnect();
      rows.disconnect();
    };
  }, []);
}
