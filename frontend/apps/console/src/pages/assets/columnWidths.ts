import { useState, type HTMLAttributes } from 'react';

import { ResizableHeader, type ResizableHeaderProps } from '@supportx/ui';

/**
 * Resizable columns for an asset list (D-147 template C; lane C's #367 review), with the same
 * header cell as the work-item lists: drag the edge, or focus it and use the arrow keys.
 *
 * `useColumnWidths` keeps each person's widths through a work-item type's `/list-settings`;
 * asset lists have no such setting yet, so the widths here last while the page is open.
 */
export function useLocalColumnWidths({
  minWidths = {},
  defaults = {},
  label,
}: {
  minWidths?: Readonly<Record<string, number>>;
  defaults?: Readonly<Record<string, number>>;
  /** The separator's name for one column, e.g. "Width of Product: use the arrow keys". */
  label: (key: string) => string;
}) {
  const [set, setSet] = useState<Readonly<Record<string, number>>>({});
  const [dragged, setDragged] = useState<{ key: string; width: number } | null>(null);
  const own = (key: string): number | undefined => set[key] ?? defaults[key];
  return {
    width: (key: string): number | undefined => (dragged?.key === key ? dragged.width : own(key)),
    header: (key: string): HTMLAttributes<HTMLElement> =>
      ({
        width: own(key),
        defaultWidth: defaults[key],
        minWidth: minWidths[key],
        resizeLabel: label(key),
        onPreview: (next: number | null) => {
          setDragged(next === null ? null : { key, width: next });
        },
        onResize: (next: number) => {
          setSet((before) => ({ ...before, [key]: next }));
        },
        onReset: () => {
          setSet((before) => Object.fromEntries(Object.entries(before).filter(([k]) => k !== key)));
        },
        // Ant Design types onHeaderCell's result as plain cell attributes; these reach the
        // ResizableHeader cell given in `components` (as in useColumnWidths).
      }) satisfies ResizableHeaderProps as HTMLAttributes<HTMLElement>,
    changed: Object.keys(set).length > 0,
    reset: () => {
      setSet({});
    },
    components: { header: { cell: ResizableHeader } },
  };
}
