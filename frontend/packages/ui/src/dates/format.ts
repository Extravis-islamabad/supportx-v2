import { useAppearance, type DateFormat, type DatePreferences } from '../appearance';
import { useTimeZone } from './time';

export interface DateTimeFormatter {
  /** Absolute date and time in the user's zone and language, e.g. "24 Oct 2026, 14:05". */
  format: (iso: string | null | undefined) => string;
  /** The same to the second, e.g. "24 Oct 2026, 14:05:09" (audit entries, REQ-AUD-003). */
  formatExact: (iso: string | null | undefined) => string;
  /** A calendar day with no time ("2026-11-02" → "2 Nov 2026"); never shifted by a zone. */
  formatDay: (day: string | null | undefined) => string;
  /** A calendar month, e.g. "October 2026". Always the UTC month (audit archives are UTC). */
  formatMonth: (iso: string | null | undefined) => string;
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
  const { intlLocale: locale, dates } = useAppearance(); // digits pinned (D-135)
  // The person's (else the organisation's) date and time format (QA10-P3-14): the date part in
  // its order and separator, the time in 24 or 12 hours, digits in the chosen system.
  const numeric = new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: zone,
  });
  const hour12 = dates.timeFormat === '12h';
  const clock = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hour12,
    timeZone: zone,
  });
  const clockExact = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12,
    timeZone: zone,
  });
  const dayIn = (formatter: Intl.DateTimeFormat, date: Date) =>
    ordered(formatter.formatToParts(date), dates.dateFormat);
  const absolute = {
    format: (date: Date) => `${dayIn(numeric, date)}, ${clock.format(date)}`,
  };
  const exact = {
    format: (date: Date) => `${dayIn(numeric, date)}, ${clockExact.format(date)}`,
  };
  const numericUtc = new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: 'UTC',
  });
  const month = new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'long',
    timeZone: 'UTC',
  });
  const day = { format: (date: Date) => dayIn(numericUtc, date) };
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
  return {
    zone,
    format: (iso) => (iso == null || iso === '' ? '' : absolute.format(new Date(iso))),
    formatExact: (iso) => (iso == null || iso === '' ? '' : exact.format(new Date(iso))),
    formatDay: (value) =>
      value == null || value === '' ? '' : day.format(new Date(`${value}T00:00:00Z`)),
    formatMonth: (iso) => (iso == null || iso === '' ? '' : month.format(new Date(iso))),
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

/** A date's day, month and year (in their digits) put in the chosen order with its separator. */
function ordered(parts: Intl.DateTimeFormatPart[], pattern: DateFormat): string {
  const part = (type: 'day' | 'month' | 'year') => parts.find((p) => p.type === type)?.value ?? '';
  const [d, m, y] = [part('day'), part('month'), part('year')];
  switch (pattern) {
    case 'mm/dd/yyyy':
      return `${m}/${d}/${y}`;
    case 'yyyy-mm-dd':
      return `${y}-${m}-${d}`;
    case 'dd.mm.yyyy':
      return `${d}.${m}.${y}`;
    default:
      return `${d}/${m}/${y}`;
  }
}

/** The pickers' dayjs format for the chosen date (and time) format. */
export function pickerFormat(dates: DatePreferences, withTime: boolean): string {
  const day = {
    'dd/mm/yyyy': 'DD/MM/YYYY',
    'mm/dd/yyyy': 'MM/DD/YYYY',
    'yyyy-mm-dd': 'YYYY-MM-DD',
    'dd.mm.yyyy': 'DD.MM.YYYY',
  }[dates.dateFormat];
  if (!withTime) return day;
  return `${day} ${dates.timeFormat === '12h' ? 'hh:mm A' : 'HH:mm'}`;
}
