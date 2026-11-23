import { fireEvent, screen, waitFor } from '@testing-library/react';
import dayjs from 'dayjs';
import { useEffect, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeApi, fakeSession } from '@supportx/api-client/testing';

import { useAppearance, type DatePreferences } from './appearance';
import {
  DateTimeField,
  DateTimeRangeField,
  instantOf,
  isKnownZone,
  useDateTime,
  wallTimeIn,
} from './dates';
import { zoneName } from './dates/time';
import { renderUi } from './test/render';

describe('time zone conversion', () => {
  it('round-trips a wall-clock time in a fixed-offset zone', () => {
    const iso = instantOf({ year: 2026, month: 10, day: 2, hour: 9, minute: 30 }, 'Asia/Dubai');
    expect(iso).toBe('2026-11-02T05:30:00.000Z');
    expect(wallTimeIn(iso, 'Asia/Dubai')).toEqual({
      year: 2026,
      month: 10,
      day: 2,
      hour: 9,
      minute: 30,
    });
  });

  it('follows daylight saving time', () => {
    const zone = 'America/New_York';
    // Summer (UTC-4) and winter (UTC-5).
    expect(instantOf({ year: 2026, month: 6, day: 1, hour: 12, minute: 0 }, zone)).toBe(
      '2026-07-01T16:00:00.000Z',
    );
    expect(instantOf({ year: 2026, month: 0, day: 15, hour: 12, minute: 0 }, zone)).toBe(
      '2026-01-15T17:00:00.000Z',
    );
    // 02:30 does not exist on 8 March 2026: the instant after the gap (03:30 EDT).
    expect(instantOf({ year: 2026, month: 2, day: 8, hour: 2, minute: 30 }, zone)).toBe(
      '2026-03-08T07:30:00.000Z',
    );
    // 01:30 happens twice on 1 November 2026: the first one (EDT).
    expect(instantOf({ year: 2026, month: 10, day: 1, hour: 1, minute: 30 }, zone)).toBe(
      '2026-11-01T05:30:00.000Z',
    );
  });

  it('knows which zones the platform supports', () => {
    expect(isKnownZone('Asia/Karachi')).toBe(true);
    expect(isKnownZone('Mars/Base')).toBe(false);
  });
});

describe('DateTimeField', () => {
  let restore: () => void = () => undefined;
  afterEach(() => {
    restore();
  });

  function session(time_zone: string | null) {
    const fake = fakeApi({ 'GET /api/v1/auth/me': { body: fakeSession({ time_zone }) } });
    restore = fake.restore;
  }

  function Harness({
    initial,
    onChange,
  }: {
    initial: string | null;
    onChange: (value: string | null) => void;
  }) {
    const [value, setValue] = useState(initial);
    return (
      <DateTimeField
        id="when"
        testId="when"
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
      />
    );
  }

  it("shows and takes times in the profile's zone, not the browser's", async () => {
    // UTC+14: differs from any developer machine or CI runner zone.
    session('Pacific/Kiritimati');
    expect(Intl.DateTimeFormat().resolvedOptions().timeZone).not.toBe('Pacific/Kiritimati');
    const changed = vi.fn();
    renderUi(<Harness initial="2026-11-02T04:00:00Z" onChange={changed} />);
    // The zone by its name in the reader's language (QA-2026-11-11 F-10), never its code.
    expect(
      await screen.findByText(`Times are in ${zoneName('Pacific/Kiritimati', 'en')}.`),
    ).toBeDefined();
    expect(screen.getByTestId('time-zone-note').getAttribute('title')).toBe('Pacific/Kiritimati');
    const input = document.getElementById('when') as HTMLInputElement;
    await waitFor(() => {
      expect(input.value).toBe('2 Nov 2026 18:00'); // the default written out, 24 hours (D-155)
    });

    fireEvent.mouseDown(input);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '3 Nov 2026 10:30' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    await waitFor(() => {
      expect(changed).toHaveBeenLastCalledWith('2026-11-02T20:30:00.000Z');
    });
  });

  it('falls back to the browser zone when the profile has none or an unknown one', async () => {
    session('Mars/Base');
    renderUi(<Harness initial={null} onChange={vi.fn()} />);
    const browser = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(await screen.findByText(`Times are in ${zoneName(browser, 'en')}.`)).toBeDefined();
  });

  it('labels the zone in Arabic too', async () => {
    session('Asia/Dubai');
    renderUi(<Harness initial={null} onChange={vi.fn()} />, { locale: 'ar' });
    // Its Arabic name; a name is isolated in the sentence (the isolation rule, packages/labels).
    await waitFor(() => {
      const note = screen.getByTestId('time-zone-note');
      expect(note.textContent.replace(/[\u2068\u2069]/g, '')).toBe(
        `الأوقات حسب ${zoneName('Asia/Dubai', 'ar')}.`,
      );
    });
  });

  it('a range shows both ends in the zone and the zone once', async () => {
    session('Asia/Dubai');
    renderUi(
      <DateTimeRangeField
        value={['2026-11-02T05:30:00Z', null]}
        onChange={vi.fn()}
        testId="range"
      />,
    );
    expect(await screen.findAllByTestId('time-zone-note')).toHaveLength(1);
    await waitFor(() => {
      const inputs = Array.from(document.querySelectorAll<HTMLInputElement>('input'));
      expect(inputs.map((i) => i.value)).toEqual(['2 Nov 2026 09:30', '']);
    });
  });
});

// QA10-P3-14: dates and pickers follow the person's (else the organisation's) date format, time
// format and first day of the week, not the browser's or a fixed medium style.
function Shown({ prefs }: { prefs: Partial<DatePreferences> }) {
  const { setDates } = useAppearance();
  const { format, formatDay } = useDateTime();
  useEffect(() => {
    setDates(prefs);
  }, [prefs, setDates]);
  return (
    <>
      <span data-testid="at">{format('2026-11-10T00:26:00Z')}</span>
      <span data-testid="day">{formatDay('2026-11-10')}</span>
    </>
  );
}

describe('date preferences (QA10-P3-14)', () => {
  it('D-155: the default writes the day out (10 Nov 2026) in 24 hours, the week from Monday', async () => {
    renderUi(<Shown prefs={{}} />);
    await waitFor(() => {
      expect(screen.getByTestId('day').textContent).toBe('10 Nov 2026');
    });
    expect(screen.getByTestId('at').textContent).toMatch(/^(9|10) Nov 2026, \d\d:26$/);
    // The pickers' calendar (dayjs's locale), set once the preferences apply.
    await waitFor(() => {
      expect(dayjs().startOf('week').day()).toBe(1);
    });
  });

  it('mm/dd/yyyy in 12 hours with a Sunday week, as chosen', async () => {
    const prefs: Partial<DatePreferences> = {
      dateFormat: 'mm/dd/yyyy',
      timeFormat: '12h',
      weekStart: 'sunday',
    };
    renderUi(<Shown prefs={prefs} />);
    await waitFor(() => {
      expect(screen.getByTestId('day').textContent).toBe('11/10/2026');
    });
    expect(screen.getByTestId('at').textContent).toMatch(/^11\/10\/2026, \d\d:26\s?(AM|PM)$/);
    await waitFor(() => {
      expect(dayjs().startOf('week').day()).toBe(0);
    });
  });
});
