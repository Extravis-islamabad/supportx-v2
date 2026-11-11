import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-045c S2: a change's Schedule tab. The implementation window and downtimes are edited
// there, the conflicts are listed with why, a save in a blocking freeze offers the override to
// those who may (only the freezes named), and a planned downtime can be announced.

const CHG_ID = '01a1a2b3-0000-7000-8000-0000000c0003';
const FREEZE = '01a1a2b3-0000-7000-8000-0000000f0001';
const DOWN_ID = '01a1a2b3-0000-7000-8000-0000000d0001';

const change = {
  ...fakeIncident({
    id: CHG_ID,
    display_id: 'CHG-12',
    subject: 'Firewall upgrade',
    status: 'implementation_scheduled',
  }),
  type: 'change',
  stage: 'implementation',
  stage_path: 'default',
  version: 9,
};

const blocked = {
  status: 409,
  body: {
    type: 'urn:supportx:problem:change_window_blocked',
    title: 'Conflict',
    status: 409,
    code: 'change_window_blocked',
    message_key: 'errors.change_window_blocked',
    params: { kind: 'freeze', window_id: FREEZE, window_ids: FREEZE, count: 1 },
    errors: [],
  },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

type Routes = NonNullable<Parameters<typeof consoleApi>[0]>['routes'];

function api(extra: Routes = {}, permissions = ['changes.view', 'changes.edit']) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['technician'] },
      {
        permissions: permissions.map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      [`GET /api/v1/changes/${CHG_ID}`]: { body: change, headers: { ETag: '"9"' } },
      [`GET /api/v1/changes/${CHG_ID}/stages`]: {
        body: {
          stage: 'implementation',
          stage_path: 'default',
          status: 'implementation_scheduled',
          version: 9,
          rail: [{ stage: 'implementation', state: 'current', optional: false, entries: [] }],
          moves: [],
        },
      },
      [`GET /api/v1/changes/${CHG_ID}/details`]: {
        body: {
          work_item_id: CHG_ID,
          version: 9,
          change_type: 'normal',
          change_reason: null,
          retrospective: false,
          sent_back: false,
        },
      },
      [`GET /api/v1/changes/${CHG_ID}/approvals`]: { body: { items: [], people: {} } },
      [`GET /api/v1/changes/${CHG_ID}/schedule`]: {
        body: [
          {
            stage: 'implementation',
            scheduled_start: null,
            scheduled_end: null,
            actual_start: null,
            actual_end: null,
            outcome: null,
            version: 0,
          },
        ],
      },
      [`GET /api/v1/changes/${CHG_ID}/downtimes`]: {
        body: [
          {
            id: DOWN_ID,
            phase: 'planned',
            kind: null,
            starts_at: '2027-03-06T22:00:00Z',
            ends_at: '2027-03-07T02:00:00Z',
            description: null,
            service_ids: [],
            ci_ids: [],
            source_work_item_id: null,
            version: 1,
          },
        ],
      },
      [`GET /api/v1/changes/${CHG_ID}/conflicts`]: {
        body: {
          items: [
            {
              kind: 'outside_maintenance',
              starts_at: '2027-03-06T22:00:00Z',
              ends_at: '2027-03-07T02:00:00Z',
              blocks: false,
              window_id: null,
              window_name: null,
              window_labels: null,
              record_id: null,
            },
          ],
          passed_window_ids: [],
        },
      },
      [`POST /api/v1/changes/${CHG_ID}/approvals/reapproval-preview`]: { body: [] },
      'GET /api/v1/changes/settings': { body: { statuses: [], closure_codes: [], own_lists: {} } },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

async function openSchedule() {
  window.history.pushState({}, '', `/changes/${CHG_ID}?tab=schedule`);
  render(<App />);
  return screen.findByTestId('change-schedule-tab');
}

async function setWindow() {
  // The picker's input in the default format (medium date, 24-hour time), then Enter.
  for (const [id, value] of [
    ['window-start', '1 Mar 2027 10:00'],
    ['window-end', '1 Mar 2027 12:00'],
  ] as const) {
    const found = await screen.findByTestId(id);
    const input = found instanceof HTMLInputElement ? found : found.querySelector('input');
    if (input === null) throw new Error('not a date field');
    fireEvent.mouseDown(input);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    fireEvent.blur(input);
  }
}

describe('console: a change’s schedule (WP-045c S2)', () => {
  it('ADR-042: lists the conflicts with why, live', async () => {
    api();
    await openSchedule();
    const panel = await screen.findByTestId('change-conflicts');
    expect(within(panel).getByTestId('conflict-outside_maintenance').textContent).toContain(
      'Outside every maintenance window',
    );
  });

  it('a window in a blocking freeze is refused, and without the override it only says why', async () => {
    api({ [`PATCH /api/v1/changes/${CHG_ID}/schedule/implementation`]: blocked });
    await openSchedule();
    await setWindow();
    fireEvent.click(await screen.findByTestId('window-save'));
    const alert = await screen.findByTestId('freeze-blocked');
    expect(alert.textContent).toContain('A freeze blocks this time');
    expect(within(alert).queryByTestId('freeze-override')).toBeNull();
  });

  it('with changes.override_freeze: the override names only the freezes refused, then saves again', async () => {
    let tries = 0;
    const fake = api(
      {
        [`PATCH /api/v1/changes/${CHG_ID}/schedule/implementation`]: () => {
          tries += 1;
          return tries === 1
            ? blocked
            : {
                body: {
                  stage: 'implementation',
                  scheduled_start: '2027-03-01T10:00:00Z',
                  scheduled_end: '2027-03-01T12:00:00Z',
                  version: 1,
                },
              };
        },
        [`POST /api/v1/changes/${CHG_ID}/freeze-override`]: { body: { version: 10 } },
      },
      ['changes.view', 'changes.edit', 'changes.override_freeze'],
    );
    await openSchedule();
    await setWindow();
    fireEvent.click(await screen.findByTestId('window-save'));
    fireEvent.click(await screen.findByTestId('freeze-override'));
    expect(screen.getByTestId('freeze-override-ok')).toHaveProperty('disabled', true);
    fireEvent.change(screen.getByTestId('freeze-override-reason'), {
      target: { value: 'The vendor only works that day' },
    });
    fireEvent.click(screen.getByTestId('freeze-override-ok'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/changes/${CHG_ID}/schedule/implementation`)).toHaveLength(
        2,
      );
    });
    const [override] = fake.find('POST', `/api/v1/changes/${CHG_ID}/freeze-override`);
    expect(override?.headers.get('If-Match')).toBe('"9"');
    expect(override?.body).toEqual({
      reason: 'The vendor only works that day',
      window_ids: [FREEZE],
    });
  });

  it('a planned downtime is announced as a draft, on the announcements form', async () => {
    api(
      {
        'GET /api/v1/announcements/settings': { body: {} },
      },
      ['changes.view', 'changes.edit', 'announcements.manage'],
    );
    await openSchedule();
    fireEvent.click(await screen.findByTestId(`downtime-${DOWN_ID}-announce`));
    await waitFor(() => {
      expect(window.location.pathname).toBe('/announcements/new');
    });
    const title = await screen.findByDisplayValue('Planned downtime: CHG-12');
    expect(title).toBeTruthy();
  });
});
