import type { DashboardWidget } from '@supportx/api-client';

import { COLUMNS, type Place } from './layout';

// The free-form grid lays out from the left edge only; in right to left each widget's column is
// mirrored on the way in and out, so the first column is on the right (D-110).

/** A grid item of react-grid-layout (only the fields we use; its types stay in FreeGrid). */
export interface GridItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
}

export function mirrored(place: Place, rtl: boolean): Place {
  return rtl ? { ...place, x: COLUMNS - place.x - place.w } : place;
}

/** The grid's layout for these widgets (mirrored in right to left). */
export function layoutOf(widgets: DashboardWidget[], rtl: boolean): GridItem[] {
  return widgets.map((w) => ({ i: w.id, ...mirrored(w.place, rtl), minW: 1, minH: 1 }));
}

/** Places back from the grid's layout (mirrored back in right to left). */
export function placesOf(layout: readonly GridItem[], rtl: boolean): Map<string, Place> {
  return new Map(
    layout.map((item) => [item.i, mirrored({ x: item.x, y: item.y, w: item.w, h: item.h }, rtl)]),
  );
}
