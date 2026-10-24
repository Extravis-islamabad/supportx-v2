import { useAppearance } from '../appearance';
import { useTimeZone } from './time';

export interface DateTimeFormatter {
  /** Absolute date and time in the user's zone and language, e.g. "24 Oct 2026, 14:05". */
  format: (iso: string | null | undefined) => string;
  /** The same instant relative to now, e.g. "in 40 minutes" / "3 hours ago". */
  relative: (iso: string | null | undefined, now?: number) => string;
  zone: string;
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
];

/**
 * The one date-time formatter (REQ-WI-014): every screen shows instants in the profile time zone
 * (else the browser's) and the UI language, and relative times come from the same instant, so a
 * header countdown and a history line can never disagree.
 */
export function useDateTime(): DateTimeFormatter {
  const zone = useTimeZone();
  const { locale } = useAppearance();
  const absolute = new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: zone,
  });
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  return {
    zone,
    format: (iso) => (iso == null || iso === '' ? '' : absolute.format(new Date(iso))),
    relative: (iso, now = Date.now()) => {
      if (iso == null || iso === '') return '';
      const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
      for (const [unit, size] of UNITS) {
        if (Math.abs(seconds) >= size || unit === 'second') {
          return rtf.format(Math.round(seconds / size), unit);
        }
      }
      return '';
    },
  };
}
