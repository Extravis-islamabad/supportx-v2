import { useState, type HTMLAttributes } from 'react';

import { useListSetting, useSaveListSetting, type ListKind } from '@supportx/api-client';

import { ResizableHeader, type ResizableHeaderProps } from './ResizableHeader';

/**
 * Resizable columns for a work-item list that has no column chooser (D-147 template C; Haider,
 * 2026-11-10): each person's widths are kept per view through the type's own `/list-settings`
 * and the same save chain as the incidents list's column moves, so quick changes never meet a
 * false conflict.
 *
 * `keys` are the list's columns in order. A column nobody resized keeps its automatic width.
 */
export function useColumnWidths({
  kind,
  viewKey,
  keys,
  minWidths = {},
  defaults = {},
  label,
  enabled = true,
}: {
  kind: ListKind;
  viewKey: string;
  keys: readonly string[];
  /** Columns that must never get narrower, e.g. `{ subject: 180 }`. */
  minWidths?: Readonly<Record<string, number>>;
  /** Columns with a width of their own (others size automatically). */
  defaults?: Readonly<Record<string, number>>;
  /** Off until the view is known: plain headers, nothing read or saved (lane A's #336 review). */
  enabled?: boolean;
  /** The separator's name for one column, e.g. "Width of Subject: use the arrow keys". */
  label: (key: string) => string;
}) {
  const setting = useListSetting(viewKey, enabled, kind);
  const save = useSaveListSetting(kind);
  const [dragged, setDragged] = useState<{ key: string; width: number } | null>(null);
  const saved = new Map((setting.data?.columns ?? []).map((c) => [c.key, c.width ?? null]));
  const savedWidth = (key: string) => saved.get(key) ?? defaults[key];
  const store = (widths: Map<string, number | null>) => {
    save.mutate({
      viewKey,
      setting: {
        columns: keys.map((key) => ({ key, width: widths.get(key) ?? null })),
        sort: setting.data?.sort ?? null,
        page_size: setting.data?.page_size ?? 50,
      },
    });
  };
  return {
    /** The width to draw the column at: a drag, else the saved one, else its own or automatic. */
    width: (key: string): number | undefined =>
      dragged?.key === key ? dragged.width : savedWidth(key),
    /** For the column's `onHeaderCell`. */
    header: (key: string): HTMLAttributes<HTMLElement> =>
      !enabled
        ? {}
        : ({
            width: savedWidth(key),
            defaultWidth: defaults[key],
            minWidth: minWidths[key],
            resizeLabel: label(key),
            onPreview: (next: number | null) => {
              setDragged(next === null ? null : { key, width: next });
            },
            onResize: (next: number) => {
              store(new Map([...saved, [key, next]]));
            },
            onReset: () => {
              store(new Map([...saved, [key, null]]));
            },
            // Ant Design types onHeaderCell's result as plain cell attributes; these reach the
            // ResizableHeader cell given in `components`.
          } satisfies ResizableHeaderProps as HTMLAttributes<HTMLElement>),
    /** Any width someone set: "Reset widths" is offered only then. */
    changed: [...saved.values()].some((w) => w !== null),
    /** Every column back to its automatic width. */
    reset: () => {
      store(new Map());
    },
    /** For the table's `components`. */
    components: { header: { cell: ResizableHeader } },
  };
}
