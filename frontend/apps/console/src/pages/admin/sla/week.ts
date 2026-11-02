import type { SlaWorkingPeriod } from '@supportx/api-client';

/** Minutes past midnight of "HH:MM" ("24:00" is 1440). */
export function minutes(hhmm: string): number {
  const [h = '0', m = '0'] = hhmm.split(':');
  return Number(h) * 60 + Number(m);
}

/** Working minutes in a week (a period whose end is not after its start runs to the next day). */
export function weekMinutes(week: SlaWorkingPeriod[]): number {
  return week.reduce((total, p) => {
    const start = minutes(p.start);
    const end = minutes(p.end);
    return total + (end > start ? end - start : 24 * 60 - start + end);
  }, 0);
}
