import dayjs, { type Dayjs } from 'dayjs';

import { currentTimeZone, useSession } from '@supportx/api-client';

import { instantOf, isKnownZone, wallTimeIn } from './zone';

/**
 * The zone dates are entered and shown in: the profile's (GET /auth/me), else the browser's,
 * else UTC. An unknown profile zone falls back the same way.
 */
export function useTimeZone(): string {
  const session = useSession();
  const profile = session.data?.user.time_zone ?? null;
  if (profile !== null && profile !== '' && isKnownZone(profile)) return profile;
  const browser = currentTimeZone();
  return browser !== undefined && isKnownZone(browser) ? browser : 'UTC';
}

/** ISO instant → the naive picker value showing its wall-clock time in `zone`. */
export function toPicker(value: string | null, zone: string): Dayjs | null {
  if (value === null || value === '') return null;
  const wall = wallTimeIn(value, zone);
  return dayjs(new Date(wall.year, wall.month, wall.day, wall.hour, wall.minute));
}

/** Naive picker value (a wall-clock time in `zone`) → ISO instant. */
export function fromPicker(value: Dayjs | null, zone: string): string | null {
  if (value === null) return null;
  return instantOf(
    {
      year: value.year(),
      month: value.month(),
      day: value.date(),
      hour: value.hour(),
      minute: value.minute(),
    },
    zone,
  );
}

/**
 * A time zone's name in the reader's language ("Pakistan Time", its Arabic), never its IANA
 * code; the code itself when the browser has no name for it (QA-2026-11-11 F-10).
 */
export function zoneName(zone: string, locale: string): string {
  try {
    const part = new Intl.DateTimeFormat(locale, { timeZone: zone, timeZoneName: 'longGeneric' })
      .formatToParts(new Date())
      .find((p) => p.type === 'timeZoneName');
    return part?.value ?? zone;
  } catch {
    return zone; // an unknown zone or an engine without `longGeneric`
  }
}
