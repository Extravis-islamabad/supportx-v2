import { useEffect } from 'react';

/**
 * Ant Design's tables (rc-table 7.54) draw a hidden row, `aria-hidden`, to measure column widths,
 * and put a copy of each column's title in it, the "select all" checkbox of a selectable table
 * included. A focusable control inside an `aria-hidden` row is an axe violation
 * (aria-hidden-focus, serious; the releases list on k3d, Cluster run 43313118567), and a keyboard
 * could reach a copy no one can see. Ant Design sets rc-table's `measureRowRender` itself, so a
 * page cannot change the row: every measure row is made `inert` here instead, which takes it out
 * of the focus order and the accessibility tree. It holds no data, only widths.
 */

const MEASURE_ROW = '.ant-table-measure-row';

function quiet(row: Element): void {
  if (!row.hasAttribute('inert')) row.setAttribute('inert', '');
}

/** Makes every table's measure row inert while mounted (once, in the appearance provider). */
export function useInertTableMeasureRows(): void {
  useEffect(() => {
    if (typeof MutationObserver === 'undefined') return undefined;
    const added = new MutationObserver((records) => {
      for (const record of records) {
        record.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          if (node.matches(MEASURE_ROW)) quiet(node);
          node.querySelectorAll(MEASURE_ROW).forEach(quiet);
        });
      }
    });
    added.observe(document.body, { childList: true, subtree: true });
    document.querySelectorAll(MEASURE_ROW).forEach(quiet);
    return () => {
      added.disconnect();
    };
  }, []);
}
