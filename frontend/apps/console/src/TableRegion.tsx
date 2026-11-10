import { useEffect, useRef, type ReactNode } from 'react';

/**
 * A table whose own scroll box (`.ant-table-content`, which scrolls sideways once the table is
 * wider than the screen: AppearanceProvider's page CSS) is a named region a keyboard can reach
 * and scroll, the way a dashboard widget's content is (axe scrollable-region-focusable, the
 * visual matrix at 390 px). The scroll box is the table's own, so it is marked in place: a
 * focusable wrapper around it would not be the element that scrolls.
 */
export function TableRegion({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = ref.current;
    if (root === null) return;
    const mark = () => {
      for (const box of root.querySelectorAll<HTMLElement>('.ant-table-content')) {
        box.setAttribute('role', 'region');
        box.setAttribute('aria-label', label);
        box.tabIndex = 0;
      }
    };
    mark();
    // The table may draw its scroll box later (loading, an empty list filling in).
    const observer = new MutationObserver(mark);
    observer.observe(root, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
    };
  }, [label]);
  return <div ref={ref}>{children}</div>;
}
