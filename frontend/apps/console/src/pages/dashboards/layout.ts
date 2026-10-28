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
