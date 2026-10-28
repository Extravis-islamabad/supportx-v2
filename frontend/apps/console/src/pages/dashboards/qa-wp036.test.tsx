import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeIncidentCatalogue } from '@supportx/api-client/testing';
import { setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';

// WP-036 QA round (~/Desktop/qa-wp036/QA-REPORT.md): one failing test per bug ID, then the fix.

// jsdom has no canvas: charts get a stand-in instance (their options are unit-tested in charts).
vi.mock('../../../../../packages/charts/node_modules/echarts/core', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  init: () => ({
    on: () => undefined,
    setOption: () => undefined,
    resize: () => undefined,
    dispose: () => undefined,
  }),
}));

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ME = '01900000-0000-7000-8000-000000000101';
const SITE = '01900000-0000-7000-8000-0000000000f1';
const OPEN = { field: 'status_category', op: 'in', value: ['open', 'paused'] };
const kpi = (id: string, extra: Record<string, unknown> = {}) => ({
  id,
  title_key: `dashboard_widget.${id}`,
  report: {
    schema_version: 1,
    entity: 'incident',
    measures: ['open_count'],
    chart: 'kpi',
    group_by: [],
    order: 'key',
    percent: false,
    ...extra,
  },
  place: { x: 0, y: 0, w: 3, h: 2 },
});
const chart = {
  id: 'open_by_priority',
  title_key: 'dashboard_widget.open_by_priority',
  report: {
    schema_version: 1,
    entity: 'incident',
    filter: OPEN,
    group_by: [{ field: 'priority', bucket: null }],
    measures: ['count'],
    chart: 'table',
    order: 'key',
    percent: false,
  },
  place: { x: 3, y: 0, w: 6, h: 4 },
};
const MY_WORK = {
  ref: 'builtin:my_work',
  builtin: 'my_work',
  name: null,
  names: {},
  description: null,
  owner_id: null,
  shared: true,
  copied_from: null,
  body: {
    widgets: [
      kpi('my_open', { filter: { field: 'technician_id', op: 'eq', value: '@me' } }),
      chart,
    ],
    filters: {},
  },
  version: 1,
  updated_at: null,
  can_edit: false,
};
const MINE = {
  ...MY_WORK,
  ref: '01900000-0000-7000-8000-00000000d001',
  builtin: null,
  name: 'Team board',
  names: { ar: 'لوحة الفريق' },
  owner_id: ME,
  shared: false,
  version: 3,
  can_edit: true,
};
const RESULT = {
  entity: 'incident',
  list_path: 'incidents',
  as_of: '2026-10-28T10:00:00Z',
  time_zone: 'UTC',
  groups: [],
  measures: [{ code: 'open_count', unit: 'count', better: 'down' }],
  rows: [],
  totals: [7],
  truncated: false,
  drill_all: OPEN,
};
const ENTITY = {
  entity: 'incident',
  list_path: 'incidents',
  fields: [
    { name: 'site_id', type: 'uuid', values: [], multiple: false, dimension: null },
    { name: 'group_id', type: 'uuid', values: [], multiple: false, dimension: null },
    { name: 'created_at', type: 'datetime', values: [], multiple: false, dimension: null },
  ],
  measures: [{ code: 'open_count', unit: 'count', better: 'down' }],
};

function routes(extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/dashboards': {
      body: { items: [MY_WORK, MINE], favourites: [], home: 'builtin:my_work', home_chosen: false },
    },
    'GET /api/v1/dashboards/builtin%3Amy_work': { body: MY_WORK },
    [`GET /api/v1/dashboards/${MINE.ref}`]: { body: MINE },
    'POST /api/v1/reports/run': { body: RESULT },
    'GET /api/v1/reports/library': {
      body: { builtin: [], folders: [], reports: [], favourites: [] },
    },
    'GET /api/v1/reports/entities/incident': { body: ENTITY },
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/custom-fields': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [{ id: SITE, name: 'Riyadh', version: 1 }] },
    'GET /api/v1/organization/departments': { body: [] },
    'GET /api/v1/organization/desks': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    ...extra,
  } as Parameters<typeof consoleApi>[0] extends { routes?: infer R } | undefined ? R : never;
}

afterEach(() => {
  restore();
});

describe('WP-036 QA fixes', () => {
  it('BUG-01: someone else saving while I edit keeps my draft, and my Done meets the conflict dialog', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', `/dashboards/${MINE.ref}`);
    // The other person's save: version 4, without the chart.
    let latest = MINE;
    const fake = api({
      me: fakeSession(),
      routes: routes({
        [`GET /api/v1/dashboards/${MINE.ref}`]: () => ({ body: latest }),
        [`PATCH /api/v1/dashboards/${MINE.ref}`]: {
          status: 409,
          body: problem(409, 'version_conflict', {
            params: {
              expected_version: 3,
              current_version: 4,
              changed_by: 'Sara Admin',
              changed_at: '2026-10-29T08:00:00Z',
              changed_fields: 'body',
            },
          }),
        },
      }),
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('dashboard-edit'));
    fireEvent.click(await screen.findByTestId('widget-wider-my_open'));

    latest = {
      ...MINE,
      version: 4,
      body: { ...MINE.body, widgets: MINE.body.widgets.slice(0, 1) },
    };
    act(() => {
      realtime.publish(':broadcast', { type: 'dashboards.changed', ids: [MINE.ref] });
    });
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/dashboards/${MINE.ref}`).length).toBeGreaterThan(1);
    });
    // Still editing, my draft still there (the chart the other person removed is still mine).
    expect(screen.getByTestId('dashboard-done')).toBeDefined();
    expect(screen.getByTestId('widget-open_by_priority')).toBeDefined();

    fireEvent.click(screen.getByTestId('dashboard-done'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/dashboards/${MINE.ref}`)).toHaveLength(1);
    });
    // The version my edit started from, never the newer one: a 409, not a silent overwrite.
    expect(fake.find('PATCH', `/api/v1/dashboards/${MINE.ref}`)[0]?.headers.get('If-Match')).toBe(
      '"3"',
    );
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Someone else changed this')).toBeDefined();
    expect(dialog.textContent).toContain('Sara Admin');
  });

  it('BUG-01 sweep: a sharing change that meets a conflict is sent again by "Keep my changes"', async () => {
    window.history.pushState({}, '', `/dashboards/${MINE.ref}`);
    let calls = 0;
    const fake = api({
      me: fakeSession({ roles: ['tenant_admin', 'technician'] }), // may share
      routes: routes({
        [`PATCH /api/v1/dashboards/${MINE.ref}`]: () => {
          calls += 1;
          return calls === 1
            ? {
                status: 409,
                body: problem(409, 'version_conflict', {
                  params: { expected_version: 3, current_version: 4, changed_by: 'Sara Admin' },
                }),
              }
            : { body: { ...MINE, shared: true, version: 5 } };
        },
      }),
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('dashboard-share'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep my changes' }));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/dashboards/${MINE.ref}`)).toHaveLength(2);
    });
    const again = fake.find('PATCH', `/api/v1/dashboards/${MINE.ref}`)[1];
    expect(again?.body).toEqual({ shared: true });
    expect(again?.headers.get('If-Match')).toBe('"4"'); // over the version they saved
  });
});
