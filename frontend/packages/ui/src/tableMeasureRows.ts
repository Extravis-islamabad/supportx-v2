import { useEffect } from 'react';

/**
 * Ant Design's tables (rc-table 7.54) draw a hidden row, `aria-hidden`, to measure column widths,
 * and put a copy of each column's title in it, the "select all" checkbox of a selectable table
 * included. A control that a keyboard can reach inside an `aria-hidden` row is an axe violation
 * (aria-hidden-focus, serious; the releases list on k3d, Cluster run 43313118567), and a person
 * could tab to a copy no one can see. Ant Design sets rc-table's `measureRowRender` itself, so a
 * page cannot change the row: every control in a measure row is taken out of the tab order here
 * (`tabindex="-1"`), which axe accepts for hidden content.
 *
 * Not `inert` on the whole row (the first version, #469): the row's own `tabIndex={-1}` is what
 * keeps a sideways-scrolling table with no rows keyboard-reachable for axe's
 * scrollable-region-focusable (the Knowledge home at 390 px, Stack smoke 43360374564).
 */

const MEASURE_ROW = '.ant-table-measure-row';
const TABBABLE =
  'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

function untab(row: Element): void {
  row.querySelectorAll(TABBABLE).forEach((control) => {
    if (control.getAttribute('tabindex') !== '-1') control.setAttribute('tabindex', '-1');
  });
}

/** Takes the controls in every table's measure row out of the tab order while mounted. */
export function useUntabbedTableMeasureRows(): void {
  useEffect(() => {
    if (typeof MutationObserver === 'undefined') return undefined;
    const added = new MutationObserver((records) => {
      for (const record of records) {
        record.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) return;
          const row = node.closest(MEASURE_ROW);
          if (row !== null) untab(row);
          node.querySelectorAll(MEASURE_ROW).forEach(untab);
        });
      }
    });
    added.observe(document.body, { childList: true, subtree: true });
    document.querySelectorAll(MEASURE_ROW).forEach(untab);
    return () => {
      added.disconnect();
    };
  }, []);
}
