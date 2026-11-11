import { instantOf, wallTimeIn } from '@supportx/ui';

// The staged types' calendar date arithmetic (WP-045c S3, shared in WP-058b S1; ADR-042 §5), in the person's time zone:
// a "day" is a wall-clock day there, never the browser's or UTC's. Pure, so it is tested alone.

export type CalendarView = 'month' | 'week' | 'day' | 'agenda' | 'timeline';

/** A wall-clock day: year, month (0-11) and day of the month. */
export interface Day {
  year: number;
  month: number;
  day: number;
}

const DAY_MS = 86_400_000;
const WEEK_MS = 7 * DAY_MS;

/** "2027-03-01": a day as a stable key (sorting, test IDs). */
export const dayKey = (d: Day): string =>
  `${String(d.year)}-${String(d.month + 1).padStart(2, '0')}-${String(d.day).padStart(2, '0')}`;

/** The wall-clock day an instant falls on in `zone`. */
export function dayOf(iso: string, zone: string): Day {
  const { year, month, day } = wallTimeIn(iso, zone);
  return { year, month, day };
}

/** A day `n` days after `d` (calendar arithmetic, not 24-hour steps: summer time is safe). */
export function addDays(d: Day, n: number): Day {
  const moved = new Date(Date.UTC(d.year, d.month, d.day + n));
  return { year: moved.getUTCFullYear(), month: moved.getUTCMonth(), day: moved.getUTCDate() };
}

/** 0 = Sunday … 6 = Saturday, for a wall-clock day. */
export const weekday = (d: Day): number => new Date(Date.UTC(d.year, d.month, d.day)).getUTCDay();

/** The first day of `d`'s week (`firstDay`: 0 Sunday, 1 Monday, 6 Saturday). */
export function weekStart(d: Day, firstDay: number): Day {
  return addDays(d, -((weekday(d) - firstDay + 7) % 7));
}

/** Midnight at the start of `d` in `zone`, as an ISO instant. */
export const startOf = (d: Day, zone: string): string =>
  instantOf({ ...d, hour: 0, minute: 0 }, zone);

/** The days a view shows around `anchor`: a month's whole weeks, a week, a day, or 30 days. */
export function daysOf(view: CalendarView, anchor: Day, firstDay: number): Day[] {
  if (view === 'day') return [anchor];
  if (view === 'week') {
    const first = weekStart(anchor, firstDay);
    return Array.from({ length: 7 }, (_, i) => addDays(first, i));
  }
  if (view === 'agenda') return Array.from({ length: 30 }, (_, i) => addDays(anchor, i));
  if (view === 'timeline') {
    // The month's own days, the 1st to the last (WP-058b S1): a row per record across them.
    const first = { ...anchor, day: 1 };
    const last = addDays(normal({ year: anchor.year, month: anchor.month + 1, day: 1 }), -1);
    return Array.from({ length: last.day }, (_, i) => addDays(first, i));
  }
  // A month: the whole weeks from the one holding the 1st to the one holding the last day.
  const first = weekStart({ ...anchor, day: 1 }, firstDay);
  const last = addDays(normal({ year: anchor.year, month: anchor.month + 1, day: 1 }), -1);
  const end = addDays(weekStart(last, firstDay), 7);
  return Array.from({ length: daysBetween(first, end) }, (_, i) => addDays(first, i));
}

/** The instants [start, end) a view's days cover, for the API's range. */
export function rangeOf(days: Day[], zone: string): { start: string; end: string } {
  const first = days[0];
  const last = days[days.length - 1];
  if (first === undefined || last === undefined) throw new Error('a view always has days');
  return { start: startOf(first, zone), end: startOf(addDays(last, 1), zone) };
}

/** Whether [start, end) touches the wall-clock day `d` in `zone`. */
export function touches(start: string, end: string, d: Day, zone: string): boolean {
  const from = Date.parse(startOf(d, zone));
  const to = Date.parse(startOf(addDays(d, 1), zone));
  return Date.parse(start) < to && from < Date.parse(end);
}

/** The view a step moves by, and where "today" is within it. */
export function step(view: CalendarView, anchor: Day, direction: 1 | -1): Day {
  if (view === 'month' || view === 'timeline')
    return { year: anchor.year, month: anchor.month + direction, day: 1 };
  if (view === 'week') return addDays(anchor, 7 * direction);
  if (view === 'agenda') return addDays(anchor, 30 * direction);
  return addDays(anchor, direction);
}

/** A month value normalised (month 12 → January next year), as `step` may give. */
export function normal(d: Day): Day {
  const n = new Date(Date.UTC(d.year, d.month, d.day));
  return { year: n.getUTCFullYear(), month: n.getUTCMonth(), day: n.getUTCDate() };
}

/** A window's occurrences touching [start, end), as the server reckons them (weekly or once). */
export function occurrences(
  window: {
    starts_at: string;
    ends_at: string;
    repeat_weekly: boolean;
    repeat_until: string | null;
  },
  start: string,
  end: string,
): { starts_at: string; ends_at: string }[] {
  const s = Date.parse(window.starts_at);
  const e = Date.parse(window.ends_at);
  const from = Date.parse(start);
  const to = Date.parse(end);
  if (!window.repeat_weekly)
    return s < to && from < e ? [{ starts_at: window.starts_at, ends_at: window.ends_at }] : [];
  const until = window.repeat_until === null ? Infinity : Date.parse(window.repeat_until);
  const length = e - s;
  const skip = from > e ? Math.floor((from - e) / WEEK_MS) : 0;
  const found: { starts_at: string; ends_at: string }[] = [];
  for (let k = skip; k < skip + 520; k += 1) {
    const begin = s + k * WEEK_MS;
    if (begin >= to || begin > until) break;
    if (begin < to && from < begin + length) {
      found.push({
        starts_at: new Date(begin).toISOString(),
        ends_at: new Date(begin + length).toISOString(),
      });
    }
  }
  return found;
}

/**
 * Move an instant by whole days, keeping its wall-clock time in `zone` (drag to another day:
 * 09:00 stays 09:00, across summer time too).
 */
export function shiftDays(iso: string, days: number, zone: string): string {
  const wall = wallTimeIn(iso, zone);
  const moved = addDays({ year: wall.year, month: wall.month, day: wall.day }, days);
  return instantOf({ ...moved, hour: wall.hour, minute: wall.minute }, zone);
}

/** Whole days from `a` to `b` (wall-clock days). */
export const daysBetween = (a: Day, b: Day): number =>
  Math.round((Date.UTC(b.year, b.month, b.day) - Date.UTC(a.year, a.month, a.day)) / DAY_MS);
