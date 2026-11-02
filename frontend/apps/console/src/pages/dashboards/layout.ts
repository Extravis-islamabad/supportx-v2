import type { DashboardBody, DashboardFilters, DashboardWidget } from '@supportx/api-client';

/** Grid columns of every dashboard (REQ-DSH-019). */
export const COLUMNS = 12;

/** Grid row height of a widget unit (REQ-DSH-019); a widget is `h` rows tall. */
export const ROW_PX = 72;

/** A widget's title: its own words, or the built-in label. */
export function widgetTitle(widget: DashboardWidget, t: (key: string) => string): string {
  return widget.title ?? (widget.title_key ? t(widget.title_key) : '');
}

export type Place = DashboardWidget['place'];

/** A dashboard body with its parts always present (the API leaves out empty ones). */
export interface Body {
  widgets: DashboardWidget[];
  filters: DashboardFilters;
}

export function normalBody(body: DashboardBody): Body {
  return { widgets: body.widgets ?? [], filters: body.filters ?? {} };
}

/** Widgets in reading order: by row, then column (narrow screens stack them this way). */
export function readingOrder(widgets: DashboardWidget[]): DashboardWidget[] {
  return [...widgets].sort((a, b) => a.place.y - b.place.y || a.place.x - b.place.x);
}

/** A place moved or resized, kept on the 12-column grid. */
export function adjust(place: Place, change: Partial<Place>): Place {
  const w = Math.min(COLUMNS, Math.max(1, change.w ?? place.w));
  const h = Math.min(12, Math.max(1, change.h ?? place.h));
  const x = Math.min(COLUMNS - w, Math.max(0, change.x ?? place.x));
  const y = Math.max(0, change.y ?? place.y);
  return { x, y, w, h };
}

function overlaps(a: Place, b: Place): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/**
 * The layout after one widget was moved or resized with the keyboard buttons, by the rules the
 * free grid uses when dragging (QA WP-036 BUG-02): the moved widget stays where it was sent,
 * whatever it now covers moves down below it (and so on), then every widget rises as far as it
 * can (vertical compaction). No two widgets ever overlap.
 */
export function settle<W extends { id: string; place: Place }>(widgets: W[], movedId: string): W[] {
  const out = widgets.map((w) => ({ ...w, place: { ...w.place } }));
  const moved = out.find((w) => w.id === movedId);
  if (moved === undefined) return out;
  const queue = [moved];
  for (let current = queue.shift(); current !== undefined; current = queue.shift()) {
    for (const other of out) {
      if (other === current || other === moved || !overlaps(current.place, other.place)) continue;
      other.place.y = current.place.y + current.place.h;
      queue.push(other);
    }
  }
  const placed: Place[] = [];
  for (const widget of readingOrder(out)) {
    while (
      widget.place.y > 0 &&
      !placed.some((p) => overlaps({ ...widget.place, y: widget.place.y - 1 }, p))
    ) {
      widget.place.y -= 1;
    }
    placed.push(widget.place);
  }
  return out;
}
