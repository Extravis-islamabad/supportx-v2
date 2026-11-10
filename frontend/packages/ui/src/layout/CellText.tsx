import type { ReactNode } from 'react';

/**
 * A list cell's text, cut with an ellipsis at its own logical end (Haider's 2026-11-10 recheck:
 * in Arabic, English names lost their start because the cell cut in the page's direction).
 * It reads in its own direction (`dir="auto"`) and keeps the column's alignment; `title` holds
 * the whole text.
 */
export function CellText({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <bdi dir="auto" className="sx-cell-text" title={title}>
      {children}
    </bdi>
  );
}
