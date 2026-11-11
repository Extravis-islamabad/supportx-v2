import { describe, expect, it } from 'vitest';

import {
  dayKey,
  dayOf,
  daysOf,
  normal,
  occurrences,
  rangeOf,
  shiftDays,
  step,
  touches,
} from './calendarMath';

// The change calendar's days are wall-clock days in the person's zone (WP-045c S3).

describe('change calendar arithmetic', () => {
  it('a month shows whole weeks from the one holding the 1st to the one holding the last', () => {
    // March 2027: Monday 1st, Wednesday 31st; weeks start on Monday.
    const days = daysOf('month', { year: 2027, month: 2, day: 15 }, 1);
    expect(days.length % 7).toBe(0);
    expect(dayKey(days[0] ?? { year: 0, month: 0, day: 0 })).toBe('2027-03-01');
    expect(dayKey(days.at(-1) ?? { year: 0, month: 0, day: 0 })).toBe('2027-04-04');
    // Weeks starting on Saturday (some tenants): the grid starts before the 1st.
    const saturday = daysOf('month', { year: 2027, month: 2, day: 15 }, 6);
    expect(dayKey(saturday[0] ?? { year: 0, month: 0, day: 0 })).toBe('2027-02-27');
  });

  it('a day is the wall-clock day in the person’s zone, not UTC', () => {
    // 21:30 UTC on 1 March is already 2 March in Karachi (UTC+5).
    expect(dayKey(dayOf('2027-03-01T21:30:00Z', 'Asia/Karachi'))).toBe('2027-03-02');
    expect(dayKey(dayOf('2027-03-01T21:30:00Z', 'UTC'))).toBe('2027-03-01');
    const range = rangeOf([{ year: 2027, month: 2, day: 2 }], 'Asia/Karachi');
    expect(range).toEqual({ start: '2027-03-01T19:00:00.000Z', end: '2027-03-02T19:00:00.000Z' });
    expect(
      touches(
        '2027-03-01T21:30:00Z',
        '2027-03-01T22:00:00Z',
        { year: 2027, month: 2, day: 2 },
        'Asia/Karachi',
      ),
    ).toBe(true);
  });

  it('moving to another day keeps the wall-clock time, across summer time', () => {
    // 09:00 in London on 27 March (GMT) moved 2 days is 09:00 on 29 March (BST).
    expect(shiftDays('2027-03-27T09:00:00Z', 2, 'Europe/London')).toBe('2027-03-29T08:00:00.000Z');
  });

  it('a weekly window repeats until its end, as the server reckons it', () => {
    const weekly = {
      starts_at: '2027-03-06T22:00:00Z',
      ends_at: '2027-03-07T04:00:00Z',
      repeat_weekly: true,
      repeat_until: '2027-03-20T00:00:00Z',
    };
    const found = occurrences(weekly, '2027-03-01T00:00:00Z', '2027-04-01T00:00:00Z');
    expect(found.map((o) => o.starts_at)).toEqual([
      '2027-03-06T22:00:00.000Z',
      '2027-03-13T22:00:00.000Z',
    ]);
    const once = { ...weekly, repeat_weekly: false, repeat_until: null };
    expect(occurrences(once, '2027-03-08T00:00:00Z', '2027-03-09T00:00:00Z')).toEqual([]);
  });

  it('steps by the view, and a month step rolls the year', () => {
    expect(normal(step('month', { year: 2027, month: 11, day: 5 }, 1))).toEqual({
      year: 2028,
      month: 0,
      day: 1,
    });
    expect(step('week', { year: 2027, month: 2, day: 1 }, -1)).toEqual({
      year: 2027,
      month: 1,
      day: 22,
    });
  });
});
