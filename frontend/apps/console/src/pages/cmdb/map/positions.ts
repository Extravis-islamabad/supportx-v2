import type { BusinessViewFilters } from '@supportx/api-client';
import type { CiMapLayout, MapPoint } from '@supportx/flow';

/** At most this many pinned positions in one business view (the API's limit). */
export const POSITIONS_MAX = 1000;

const CI_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * The positions a business view keeps: CIs only, by their IDs. A restricted placeholder's key
 * means nothing in the next answer, so it is never saved (and its spot is found again).
 */
export function positionsOut(
  positions: ReadonlyMap<string, MapPoint>,
): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  let n = 0;
  for (const [key, p] of positions) {
    if (!CI_ID.test(key) || n >= POSITIONS_MAX) continue;
    out[key] = { x: Math.round(p.x), y: Math.round(p.y) };
    n += 1;
  }
  return out;
}

/** A business view's saved positions as the map takes them. */
export function positionsIn(
  saved: Record<string, { x: number; y: number }> | undefined,
): Map<string, MapPoint> {
  return new Map(Object.entries(saved ?? {}).map(([key, p]) => [key, { x: p.x, y: p.y }]));
}

/** A map's layout and filters, as a business view keeps them. */
export interface MapSettings {
  layout: CiMapLayout;
  filters: BusinessViewFilters;
}

export const DEFAULT_FILTERS: BusinessViewFilters = {
  relationship_type_ids: [],
  ci_type_ids: [],
  show_eol: false,
  depth: 1,
};

/** Typed text, trimmed; nothing typed is null (an optional description). */
export function textOrNull(value: string | undefined): string | null {
  const text = value?.trim() ?? '';
  return text === '' ? null : text;
}
