import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-045c S3: the change calendar. Changes by their implementation window and planned
// downtimes, freezes and maintenance windows as layers, wall-clock days in the person's zone,
// and a change dragged to another day keeps its time and carries its window's If-Match.

const CHG_ID = '01a1a2b3-0000-7000-8000-0000000c0004';
const FREEZE = '01a1a2b3-0000-7000-8000-0000000f0002';

const entry = {
  record_id: CHG_ID,
  display_id: 'CHG-20',
  subject: 'Core switch firmware',
  stage: 'implementation',
  status: 'implementation_scheduled',
  stage_path: 'default',
  group_id: null,
  site_id: null,
  technician_id: null,
  kind: 'window',
  starts_at: '2027-03-10T09:00:00Z',
  ends_at: '2027-03-10T11:00:00Z',
  part_id: null,
  version: 3,
};

const freeze = {
  id: FREEZE,
  kind: 'freeze',
  mode: 'block',
  name: 'Quarter end',
  labels: null,
  description: null,
  starts_at: '2027-03-29T00:00:00Z',
  ends_at: '2027-03-31T00:00:00Z',
  repeat_weekly: false,
  repeat_until: null,
  site_ids: [],
  group_ids: [],
  service_ids: [],
  ci_ids: [],
  version: 1,
};

let restore: () => void = () => undefined;
beforeEach(() => {
  // "Today" is 10 March 2027 (the month shown first).
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2027-03-10T08:00:00Z'));
});
afterEach(() => {
  vi.useRealTimers();
  restore();
});

type Routes = NonNullable<Parameters<typeof consoleApi>[0]>['routes'];

function api(extra: Routes = {}) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['technician'] },
      {
        permissions: ['changes.view', 'changes.edit'].map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      'GET /api/v1/change-calendar': { body: [entry] },
      'GET /api/v1/change-windows': { body: [freeze] },
      [`POST /api/v1/changes/${CHG_ID}/approvals/reapproval-preview`]: { body: [] },
      [`PATCH /api/v1/changes/${CHG_ID}/schedule/implementation`]: {
        body: {
          stage: 'implementation',
          scheduled_start: '2027-03-12T09:00:00Z',
          scheduled_end: '2027-03-12T11:00:00Z',
          version: 4,
        },
      },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: the change calendar (WP-045c S3)', () => {
  it('shows a month with the change on its day and the freeze across its days', async () => {
    window.history.pushState({}, '', '/changes/calendar');
    const fake = api();
    render(<App />);
    const day = await screen.findByTestId('calendar-day-2027-03-10');
    await waitFor(() => {
      expect(within(day).getByTestId('calendar-entry-CHG-20-window').textContent).toContain(
        'Core switch firmware',
      );
    });
    expect(
      within(screen.getByTestId('calendar-day-2027-03-29')).getByTestId(`calendar-window-${FREEZE}`)
        .textContent,
    ).toBe('Quarter end');
    // The range asked for is the grid's: whole weeks around March.
    const asked = fake.find('GET', '/api/v1/change-calendar')[0];
    expect(asked?.url.searchParams.get('mine')).toBe('false');
    expect(Date.parse(asked?.url.searchParams.get('start') ?? '')).toBeLessThanOrEqual(
      Date.parse('2027-03-01T00:00:00Z'),
    );
    // The freeze layer can be hidden.
    fireEvent.click(screen.getByLabelText('Freeze'));
    expect(screen.queryByTestId(`calendar-window-${FREEZE}`)).toBeNull();
  });

  it('dragging a change to another day keeps its time and sends its window’s If-Match', async () => {
    window.history.pushState({}, '', '/changes/calendar');
    const fake = api();
    render(<App />);
    const chip = await screen.findByTestId('calendar-entry-CHG-20-window');
    const data = new Map<string, string>();
    const dataTransfer = {
      setData: (k: string, v: string) => data.set(k, v),
      getData: (k: string) => data.get(k) ?? '',
      effectAllowed: 'move',
    };
    fireEvent.dragStart(chip, { dataTransfer });
    const target = screen.getByTestId('calendar-day-2027-03-12');
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/changes/${CHG_ID}/schedule/implementation`)).toHaveLength(
        1,
      );
    });
    const [moved] = fake.find('PATCH', `/api/v1/changes/${CHG_ID}/schedule/implementation`);
    expect(moved?.headers.get('If-Match')).toBe('"3"');
    expect(moved?.body).toEqual({
      scheduled_start: '2027-03-12T09:00:00.000Z',
      scheduled_end: '2027-03-12T11:00:00.000Z',
    });
  });

  it('lane C: the keyboard moves a change through the same reschedule as a drag', async () => {
    window.history.pushState({}, '', '/changes/calendar');
    const fake = api();
    render(<App />);
    fireEvent.click(await screen.findByTestId('calendar-move-CHG-20'));
    const input = await screen.findByTestId('calendar-move-day');
    fireEvent.mouseDown(input);
    fireEvent.change(input, { target: { value: '12 Mar 2027' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    fireEvent.click(screen.getByTestId('calendar-move-ok'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/changes/${CHG_ID}/schedule/implementation`)).toHaveLength(
        1,
      );
    });
    const [moved] = fake.find('PATCH', `/api/v1/changes/${CHG_ID}/schedule/implementation`);
    expect(moved?.body).toEqual({
      scheduled_start: '2027-03-12T09:00:00.000Z',
      scheduled_end: '2027-03-12T11:00:00.000Z',
    });
  });

  it('lane C: every grid cell sits in a row (axe aria-required-children)', async () => {
    window.history.pushState({}, '', '/changes/calendar');
    api();
    render(<App />);
    const grid = await screen.findByTestId('calendar-month');
    for (const cell of grid.querySelectorAll('[role="gridcell"], [role="columnheader"]')) {
      expect(cell.parentElement?.getAttribute('role')).toBe('row');
    }
    expect(grid.querySelectorAll('[role="row"]').length).toBeGreaterThan(4);
  });

  it('the agenda lists only the days with something on them', async () => {
    window.history.pushState({}, '', '/changes/calendar');
    api();
    render(<App />);
    await screen.findByTestId('calendar-day-2027-03-10');
    fireEvent.click(screen.getByText('Agenda'));
    const agenda = await screen.findByTestId('calendar-agenda');
    expect(within(agenda).getByTestId('calendar-day-2027-03-10')).toBeTruthy();
    expect(within(agenda).queryByTestId('calendar-day-2027-03-11')).toBeNull();
  });
});
