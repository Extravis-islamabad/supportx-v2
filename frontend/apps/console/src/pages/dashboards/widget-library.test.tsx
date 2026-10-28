import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';
import { recordsQuery, widgetDefinition, withViewer } from './widgetDefinition';

// The dashboard widget library (D-114): the catalogue, records widgets and flow reports.

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

const ME = fakeSession().user.id;
const OPEN = { field: 'status_category', op: 'in', value: ['open', 'paused'] };
const MINE_LIST = {
  id: 'my_open_list',
  title_key: 'dashboard_widget.my_open_list',
  records: {
    entity: 'incident',
    filter: { and: [OPEN, { field: 'technician_id', op: 'eq', value: '@me' }] },
    sort: 'priority',
    limit: 5,
  },
  place: { x: 0, y: 0, w: 6, h: 4 },
};
const FLOW = {
  id: 'created_vs_resolved',
  title_key: 'dashboard_widget.created_vs_resolved',
  report: {
    schema_version: 1,
    entity: 'incident',
    measures: ['flow_created', 'flow_resolved'],
    flow: { days: 30, bucket: 'day' },
    group_by: [],
    chart: 'line',
    order: 'key',
    percent: false,
  },
  place: { x: 6, y: 0, w: 6, h: 4 },
};
const BOARD = {
  ref: '01900000-0000-7000-8000-00000000d002',
  builtin: null,
  name: 'Desk board',
  names: {},
  description: null,
  owner_id: ME,
  shared: false,
  copied_from: null,
  body: { widgets: [MINE_LIST, FLOW], filters: {} },
  version: 2,
  updated_at: null,
  can_edit: true,
};
const FLOW_RESULT = {
  entity: 'incident',
  list_path: 'incidents',
  as_of: '2026-10-28T10:00:00Z',
  time_zone: 'UTC',
  groups: [{ field: 'created_at', bucket: 'day', kind: 'datetime', label_prefix: null }],
  measures: [
    { code: 'flow_created', unit: 'count', better: 'neutral' },
    { code: 'flow_resolved', unit: 'count', better: 'up' },
  ],
  rows: [{ keys: ['2026-10-28T00:00:00'], values: [3, 1], drill: OPEN }],
  totals: [3, 1],
  truncated: false,
  drill_all: null,
};
const entry = (code: string, section: string, extra: Record<string, unknown> = {}) => ({
  code,
  module: 'incidents',
  section,
  title_key: `dashboard_widget.${code}`,
  widget: {
    id: code,
    title_key: `dashboard_widget.${code}`,
    report: {
      schema_version: 1,
      entity: 'incident',
      measures: ['overdue_count'],
      chart: 'kpi',
      group_by: [],
      order: 'key',
      percent: false,
    },
    report_ref: null,
    records: null,
    place: { x: 0, y: 0, w: 3, h: 2 },
  },
  coming_with: null,
  ...extra,
});
const CATALOGUE = {
  sections: ['key_numbers', 'queues', 'coming_later'],
  entries: [
    entry('overdue', 'key_numbers'),
    entry('due_today', 'key_numbers'),
    entry('sla_breached', 'coming_later', { coming_with: 'sla' }),
  ],
};

function routes(extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/dashboards': {
      body: { items: [BOARD], favourites: [], home: BOARD.ref, home_chosen: true },
    },
    [`GET /api/v1/dashboards/${BOARD.ref}`]: { body: BOARD },
    'GET /api/v1/dashboards/widgets': { body: CATALOGUE },
    'POST /api/v1/reports/run': { body: FLOW_RESULT },
    'GET /api/v1/reports/library': {
      body: { builtin: [], folders: [], reports: [], favourites: [] },
    },
    'GET /api/v1/reports/entities/incident': {
      body: { entity: 'incident', list_path: 'incidents', fields: [], measures: [] },
    },
    'GET /api/v1/incidents': {
      body: {
        items: [
          fakeIncident({ display_id: 'INC-7', subject: 'Mail is down', priority: 'p1' }),
          fakeIncident({ display_id: 'INC-8', subject: 'Printer jam', priority: 'p4' }),
        ],
        has_more: false,
        next_cursor: null,
        total: 2,
      },
    },
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/custom-fields': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/organization/departments': { body: [] },
    'GET /api/v1/organization/desks': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    ...extra,
  } as Parameters<typeof consoleApi>[0] extends { routes?: infer R } | undefined ? R : never;
}

describe('widget library rules (D-114)', () => {
  it('leaves "my groups" for the server and puts the viewer in for "me"', () => {
    const tree = { and: [{ value: '@me' }, { value: '@my_groups' }] };
    expect(withViewer(tree, 'u1')).toEqual({ and: [{ value: 'u1' }, { value: '@my_groups' }] });
  });

  it('a created-vs-resolved report keeps its own range; a list is not a report', () => {
    const run = widgetDefinition(FLOW as never, {
      userId: 'u1',
      filters: { days: 7, site_id: 's1' },
      builtin: [],
    });
    expect(JSON.stringify(run?.filter)).not.toContain('last_n_days'); // the bar's range skipped
    expect(JSON.stringify(run?.filter)).toContain('s1'); // the site still applies
    expect(widgetDefinition(MINE_LIST as never, { userId: 'u1', filters: {}, builtin: [] })).toBe(
      null,
    );
  });

  it('a records widget asks the list for its filter, order and size, as the viewer', () => {
    const query = recordsQuery(MINE_LIST.records as never, {
      userId: 'u1',
      filters: { group_id: 'g1' },
    });
    expect(query.sort).toBe('priority');
    expect(query.limit).toBe(5);
    expect(JSON.stringify(query.filter)).toContain('"u1"');
    expect(JSON.stringify(query.filter)).toContain('"g1"');
    expect(JSON.stringify(query.filter)).not.toContain('@me');
  });
});

describe('widget library on screen (D-114)', () => {
  afterEach(() => {
    restore();
  });

  it("a records widget lists the viewer's records and opens one; a flow chart is not a tile", async () => {
    window.history.pushState({}, '', `/dashboards/${BOARD.ref}`);
    const fake = api({ me: fakeSession(), routes: routes() });
    render(<App />);
    const list = await screen.findByTestId('widget-my_open_list');
    expect(await within(list).findByText('Mail is down')).toBeDefined();
    expect(within(list).getByTestId('widget-record-INC-8')).toBeDefined();
    const asked = fake.find('GET', '/api/v1/incidents')[0]?.url ?? '';
    expect(decodeURIComponent(asked)).toContain(ME); // "me" is the viewer
    expect(decodeURIComponent(asked)).toContain('sort=priority');
    expect(screen.getByTestId('widget-title-my_open_list').textContent).toBe('My open work');
    // The flow widget is a chart with a type switch, never a single-number tile.
    expect(await screen.findByTestId('widget-type-created_vs_resolved')).toBeDefined();
    expect(
      within(screen.getByTestId('widget-created_vs_resolved')).queryByTestId('widget-kpi-value'),
    ).toBeNull();
  });

  it('Add widget opens on the searchable catalogue; coming-later widgets cannot be picked', async () => {
    window.history.pushState({}, '', `/dashboards/${BOARD.ref}`);
    const fake = api({
      me: fakeSession(),
      routes: routes({
        [`PATCH /api/v1/dashboards/${BOARD.ref}`]: { body: { ...BOARD, version: 3 } },
      }),
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('dashboard-edit'));
    fireEvent.click(await screen.findByTestId('dashboard-add-widget'));
    const catalogue = await screen.findByTestId('dashboard-catalogue');
    expect(within(catalogue).getByText('Key numbers')).toBeDefined();
    expect(within(catalogue).getByText('Arrives with SLA management')).toBeDefined();
    const later = screen.getByRole('radio', { name: /SLA breached/ });
    expect((later as HTMLInputElement).disabled).toBe(true);

    fireEvent.change(screen.getByTestId('dashboard-catalogue-search'), {
      target: { value: 'today' },
    });
    expect(screen.queryByRole('radio', { name: /^Overdue/ })).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: /Due today/ }));
    fireEvent.click(await screen.findByTestId('dashboard-add-confirm'));
    fireEvent.click(screen.getByTestId('dashboard-done'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/dashboards/${BOARD.ref}`)).toHaveLength(1);
    });
    const body = fake.find('PATCH', `/api/v1/dashboards/${BOARD.ref}`)[0]?.body as {
      body: { widgets: { title_key: string | null; place: { y: number } }[] };
    };
    const added = body.body.widgets[2];
    expect(added?.title_key).toBe('dashboard_widget.due_today');
    expect(added?.place.y).toBe(4); // under the others
    expect(document.body.textContent).not.toMatch(/dashboard_widget\.|widget_section\./);
  });
});
