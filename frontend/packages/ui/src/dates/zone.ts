/**
 * Instants ↔ wall-clock time in a named IANA zone, with the platform's Intl data only.
 *
 * Pickers show and return naive local dates; the form keeps ISO instants (UTC). Converting
 * through these helpers makes the picker show the user's profile zone even when the browser
 * runs in another one (D-035). Not using the dayjs timezone plugin on purpose: its objects
 * misbehave when pickers set hours on them across DST, and a locale with its own digits (ar)
 * would leak into formatted strings.
 */

export interface WallTime {
  year: number;
  /** 0-based, like Date. */
  month: number;
  day: number;
  hour: number;
  minute: number;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(zone: string): Intl.DateTimeFormat {
  let found = formatters.get(zone);
  if (found === undefined) {
    found = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    formatters.set(zone, found);
  }
  return found;
}

/** Whether the platform knows the zone (a profile may hold one it does not). */
export function isKnownZone(zone: string): boolean {
  try {
    formatter(zone);
    return true;
  } catch {
    return false;
  }
}

function parts(epochMs: number, zone: string): WallTime & { second: number } {
  const values: Record<string, number> = {};
  for (const part of formatter(zone).formatToParts(new Date(epochMs))) {
    if (part.type !== 'literal') values[part.type] = Number(part.value);
  }
  const get = (name: string) => values[name] ?? 0;
  return {
    year: get('year'),
    month: get('month') - 1,
    day: get('day'),
    hour: get('hour'),
    minute: get('minute'),
    second: get('second'),
  };
}

/** The wall-clock time of an ISO instant in `zone`. */
export function wallTimeIn(iso: string, zone: string): WallTime {
  const { year, month, day, hour, minute } = parts(Date.parse(iso), zone);
  return { year, month, day, hour, minute };
}

/** How far `zone` is ahead of UTC at an instant (ms). */
function offsetAt(epochMs: number, zone: string): number {
  const whole = Math.floor(epochMs / 1000) * 1000;
  const p = parts(whole, zone);
  return Date.UTC(p.year, p.month, p.day, p.hour, p.minute, p.second) - whole;
}

/**
 * The ISO instant of a wall-clock time in `zone`. A time skipped by a DST change resolves to
 * the instant after the gap; a repeated one to its first occurrence.
 */
export function instantOf(wall: WallTime, zone: string): string {
  const asUtc = Date.UTC(wall.year, wall.month, wall.day, wall.hour, wall.minute);
  const first = offsetAt(asUtc, zone);
  let instant = asUtc - first;
  const second = offsetAt(instant, zone);
  if (second !== first) {
    const retry = asUtc - second;
    instant = offsetAt(retry, zone) === second ? retry : Math.max(instant, retry);
  }
  return new Date(instant).toISOString();
}
