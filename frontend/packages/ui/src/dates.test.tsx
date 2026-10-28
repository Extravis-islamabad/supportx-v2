import { fireEvent, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeApi, fakeSession } from '@supportx/api-client/testing';

import { DateTimeField, DateTimeRangeField, instantOf, isKnownZone, wallTimeIn } from './dates';
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
    expect(await screen.findByText('Times are in Pacific/Kiritimati.')).toBeDefined();
    const input = document.getElementById('when') as HTMLInputElement;
    await waitFor(() => {
      expect(input.value).toBe('2026-11-02 18:00');
    });

    fireEvent.mouseDown(input);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '2026-11-03 10:30' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    await waitFor(() => {
      expect(changed).toHaveBeenLastCalledWith('2026-11-02T20:30:00.000Z');
    });
  });

  it('falls back to the browser zone when the profile has none or an unknown one', async () => {
    session('Mars/Base');
    renderUi(<Harness initial={null} onChange={vi.fn()} />);
    const browser = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(await screen.findByText(`Times are in ${browser}.`)).toBeDefined();
  });

  it('labels the zone in Arabic too', async () => {
    session('Asia/Dubai');
    renderUi(<Harness initial={null} onChange={vi.fn()} />, { locale: 'ar' });
    // A Latin zone name in Arabic text is isolated (the isolation rule, packages/labels).
    expect(await screen.findByText('الأوقات بتوقيت \u2068Asia/Dubai\u2069.')).toBeDefined();
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
      expect(inputs.map((i) => i.value)).toEqual(['2026-11-02 09:30', '']);
    });
  });
});
