// An asset's age (REQ-AST-011): whole years, months and days between two calendar days. The
// same rule as backend app/modules/assets/domain/assets.py `age` (same test cases), computed
// here so switching the tenant's age basis recalculates every age live (AC2).

import dayjs from 'dayjs';

export interface Age {
  years: number;
  months: number;
  days: number;
}

const DAY_MS = 24 * 3600 * 1000;

function parts(day: string): [number, number, number] | null {
  const found = /^(\d{4})-(\d{2})-(\d{2})/.exec(day);
  if (found === null) return null;
  return [Number(found[1]), Number(found[2]), Number(found[3])];
}

function daysIn(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate(); // month is 1-based here
}

/** From `since` to `today` (both YYYY-MM-DD); null for a future or unreadable date. */
export function ageBetween(since: string, today: string): Age | null {
  const from = parts(since);
  const to = parts(today);
  if (from === null || to === null) return null;
  const [sy, sm, sd] = from;
  const [ty, tm, td] = to;
  const start = Date.UTC(sy, sm - 1, sd);
  const end = Date.UTC(ty, tm - 1, td);
  if (start > end) return null;
  let months = (ty - sy) * 12 + tm - sm;
  if (td < sd) months -= 1;
  // The day count runs from the same day of the last whole month, clamped to month ends.
  const anchor = sm + months;
  const year = sy + Math.floor((anchor - 1) / 12);
  const month = ((anchor - 1) % 12) + 1;
  const day = Math.min(sd, daysIn(year, month));
  const days = Math.round((end - Date.UTC(year, month - 1, day)) / DAY_MS);
  return { years: Math.floor(months / 12), months: months % 12, days };
}

/** The basis day of an asset for the tenant's setting; null when it has none (AC3: unknown). */
export function basisDay(
  basis: 'acquisition_date' | 'created_date',
  asset: { acquired_on: string | null; created_at: string },
): string | null {
  // The creation day where the viewer is, like "today" it is compared with: the UTC date of the
  // timestamp would make a new asset a day old after local midnight east of UTC.
  return basis === 'acquisition_date'
    ? asset.acquired_on
    : dayjs(asset.created_at).format('YYYY-MM-DD');
}
