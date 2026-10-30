import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';
import { kpiPeriod, previousPeriod, sparkline, trend } from './kpi';
import { layoutOf, mirrored, placesOf } from './gridMirror';
import { adjust, readingOrder } from './layout';
import { unusableFilters, widgetDefinition, withViewer } from './widgetDefinition';

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

describe('dashboards: rules without a screen', () => {
  it('puts the viewer in place of "me" and adds the filter bar (REQ-DSH-022)', () => {
    expect(withViewer({ and: [{ value: '@me' }, { value: ['@me', 'x'] }] }, 'u1')).toEqual({
      and: [{ value: 'u1' }, { value: ['u1', 'x'] }],
    });
    const definition = widgetDefinition(MY_WORK.body.widgets[0] as never, {
      userId: 'u1',
      filters: { site_id: SITE, days: 30 },
      builtin: [],
      fields: ENTITY.fields,
    });
    expect(definition?.filter).toEqual({
      and: [
        { field: 'technician_id', op: 'eq', value: 'u1' },
        { field: 'site_id', op: 'eq', value: SITE },
      ],
    });
    // D-119: that widget counts what is open now; a volume widget does take the time filter.
    const volume = { ...MY_WORK.body.widgets[0]?.report, filter: undefined, measures: ['count'] };
    expect(
      widgetDefinition({ id: 'v', report: volume } as never, {
        userId: 'u1',
        filters: { days: 30 },
        builtin: [],
        fields: ENTITY.fields,
      })?.filter,
    ).toEqual({ field: 'created_at', op: 'last_n_days', value: 30 });
    // REQ-DSH-022 AC2: an entity without the field is not filtered by it, and says so.
    expect(unusableFilters({ group_id: 'g' }, [ENTITY.fields[0]] as never)).toEqual(['group_id']);
  });

  it('finds a KPI period, its previous period, its sparkline and whether a rise is good (REQ-DSH-008)', () => {
    const definition = {
      ...MY_WORK.body.widgets[0]?.report,
      filter: { and: [OPEN, { field: 'resolved_at', op: 'last_n_days', value: 7 }] },
    } as never;
    const period = kpiPeriod(definition) ?? { field: '', days: 0 };
    expect(period).toEqual({ field: 'resolved_at', days: 7 });
    const before = previousPeriod(definition, period, new Date('2026-10-28T00:00:00Z'));
    expect(JSON.stringify(before.filter)).toContain('"op":"between"');
    expect(JSON.stringify(before.filter)).toContain('2026-10-14');
    expect(sparkline(definition, period).group_by).toEqual([
      { field: 'resolved_at', bucket: 'week' },
    ]);
    expect(trend(10, 8, 'down')).toEqual({ delta: 2, good: false }); // more open work is bad
    expect(trend(95, 90, 'up')).toEqual({ delta: 5, good: true }); // more compliance is good
    expect(kpiPeriod({ ...(definition as object), filter: OPEN } as never)).toBeNull();
  });

  it('keeps moved and resized widgets on the 12-column grid and stacks them in reading order', () => {
    expect(adjust({ x: 10, y: 0, w: 2, h: 2 }, { w: 4 })).toEqual({ x: 8, y: 0, w: 4, h: 2 });
    expect(adjust({ x: 0, y: 0, w: 2, h: 2 }, { x: -1, h: 0 })).toEqual({ x: 0, y: 0, w: 2, h: 1 });
    const order = readingOrder([
      { ...chart, id: 'b', place: { x: 6, y: 0, w: 6, h: 2 } },
      { ...chart, id: 'c', place: { x: 0, y: 2, w: 6, h: 2 } },
      { ...chart, id: 'a', place: { x: 0, y: 0, w: 6, h: 2 } },
    ] as never);
    expect(order.map((w: { id: string }) => w.id)).toEqual(['a', 'b', 'c']);
  });
});

describe('free-form grid (D-110)', () => {
  it('mirrors columns in right to left on the way in and back on the way out', () => {
    const place = { x: 0, y: 1, w: 3, h: 2 };
    expect(mirrored(place, true)).toEqual({ x: 9, y: 1, w: 3, h: 2 }); // first column on the right
    expect(mirrored(place, false)).toEqual(place);
    const widgets = [{ ...chart, id: 'a', place }] as never;
    for (const rtl of [true, false]) {
      expect(placesOf(layoutOf(widgets, rtl), rtl).get('a')).toEqual(place); // a round trip
    }
    // In Arabic, dragging one column to the visual right moves one column towards the start.
    const middle = [{ ...chart, id: 'm', place: { x: 3, y: 0, w: 3, h: 2 } }] as never;
    const dragged = layoutOf(middle, true).map((item) => ({ ...item, x: item.x + 1 }));
    expect(placesOf(dragged, true).get('m')?.x).toBe(2);
  });
});

describe('dashboards on screen', () => {
  afterEach(() => {
    restore();
  });

  it('REQ-DSH-001/002: the home page shows the role home, live, with labelled widgets', async () => {
    window.history.pushState({}, '', '/');
    const fake = api({ me: fakeSession(), routes: routes() });
    render(<App />);
    expect((await screen.findByTestId('dashboard-title')).textContent).toBe('My work');
    expect((await screen.findByTestId('widget-title-my_open')).textContent).toBe(
      'My open incidents',
    );
    await waitFor(() => {
      expect(screen.getAllByTestId('widget-kpi-value')[0]?.textContent).toBe('7');
    });
    // "me" is the viewer when it runs (REQ-DSH-028: each viewer's own scope).
    const runs = fake.find('POST', '/api/v1/reports/run');
    expect(JSON.stringify(runs.map((r) => r.body))).toContain(fakeSession().user.id);
    expect(JSON.stringify(runs.map((r) => r.body))).not.toContain('@me');
    expect(document.body.textContent).not.toMatch(/dashboard_widget\.|builtin:/);
  });

  it('REQ-DSH-005: favourites first, then ready-made, shared and mine; starring moves it', async () => {
    window.history.pushState({}, '', '/dashboards');
    const fake = api({
      me: fakeSession(),
      routes: routes({
        'PUT /api/v1/dashboards/favourites/builtin%3Amy_work': { status: 204 },
      }),
    });
    render(<App />);
    const builtin = await screen.findByTestId('dashboards-group-builtin');
    expect(within(builtin).getByText('My work')).toBeDefined();
    expect(
      within(screen.getByTestId('dashboards-group-mine')).getByText('Team board'),
    ).toBeDefined();
    fireEvent.change(screen.getByTestId('dashboards-search'), {
      target: { value: 'team' },
    });
    await waitFor(() => {
      expect(screen.queryByTestId('dashboards-group-builtin')).toBeNull();
    });
    fireEvent.change(screen.getByTestId('dashboards-search'), {
      target: { value: '' },
    });
    fireEvent.click(await screen.findByTestId('dashboards-star-builtin:my_work'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/dashboards/favourites/builtin%3Amy_work')).toHaveLength(1);
    });
  });

  it('REQ-DSH-022: the site filter reaches every widget in one step', async () => {
    window.history.pushState({}, '', '/dashboards/builtin%3Amy_work');
    const fake = api({ me: fakeSession(), routes: routes() });
    render(<App />);
    await screen.findByTestId('widget-title-my_open');
    const site = screen.getByTestId('dashboard-filter-site');
    fireEvent.mouseDown(site.querySelector('.ant-select-selector') ?? site);
    fireEvent.click(await screen.findByTitle('Riyadh'));
    await waitFor(() => {
      const runs = fake.find('POST', '/api/v1/reports/run').map((r) => JSON.stringify(r.body));
      expect(runs.filter((r) => r.includes(SITE)).length).toBeGreaterThanOrEqual(2);
    });
  });

  it('REQ-DSH-019: edit mode moves, resizes, removes and undoes; Done saves with If-Match', async () => {
    window.history.pushState({}, '', `/dashboards/${MINE.ref}`);
    const fake = api({
      me: fakeSession(),
      routes: routes({
        [`PATCH /api/v1/dashboards/${MINE.ref}`]: { body: { ...MINE, version: 4 } },
      }),
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('dashboard-edit'));
    fireEvent.click(await screen.findByTestId('widget-move_right-my_open'));
    fireEvent.click(screen.getByTestId('widget-wider-my_open'));
    fireEvent.click(screen.getByTestId('widget-remove-open_by_priority'));
    expect(screen.queryByTestId('widget-open_by_priority')).toBeNull();
    fireEvent.click(screen.getByTestId('dashboard-undo')); // the removal comes back (AC3)
    expect(await screen.findByTestId('widget-open_by_priority')).toBeDefined();
    fireEvent.click(screen.getByTestId('dashboard-done'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/dashboards/${MINE.ref}`)).toHaveLength(1);
    });
    const call = fake.find('PATCH', `/api/v1/dashboards/${MINE.ref}`)[0];
    expect(call?.headers.get('If-Match')).toBe('"3"');
    const body = call?.body as {
      body: { widgets: { id: string; place: { x: number; w: number } }[] };
    };
    expect(body.body.widgets.map((w) => w.id)).toEqual(['my_open', 'open_by_priority']);
    expect(body.body.widgets[0]?.place).toMatchObject({ x: 1, w: 4 });
  });

  it('REQ-DSH-028 AC2: a dashboard no longer shared with the viewer says so', async () => {
    window.history.pushState({}, '', `/dashboards/${MINE.ref}`);
    api({
      me: fakeSession(),
      routes: routes({
        [`GET /api/v1/dashboards/${MINE.ref}`]: {
          status: 404,
          body: problem(404, 'dashboard_not_found'),
        },
      }),
    });
    render(<App />);
    expect(await screen.findByTestId('dashboard-gone')).toBeDefined();
    expect(
      screen.getByText('This dashboard does not exist or is not shared with you.'),
    ).toBeDefined();
  });

  describe('in Arabic', () => {
    beforeEach(() => {
      window.history.pushState({}, '', `/dashboards/${MINE.ref}`);
    });

    it('REQ-DSH-045/046: right to left, the Arabic name, labels only', async () => {
      api({ me: fakeSession({ locale: 'ar' }), routes: routes() });
      render(<App />);
      expect((await screen.findByTestId('dashboard-title')).textContent).toBe('لوحة الفريق');
      expect(document.documentElement.dir).toBe('rtl');
      expect((await screen.findByTestId('widget-title-open_by_priority')).textContent).toBe(
        'المفتوحة حسب الأولوية',
      );
      expect(document.body.textContent).not.toMatch(/dashboard_widget\.|dashboards\./);
    });
  });
});
