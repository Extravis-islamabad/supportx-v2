import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';
import type { ReportWords } from '../../reports/names';
import {
  builderFields,
  chipsFilter,
  exportFilter,
  quarterOf,
  rangeFilter,
  skipReason,
} from './model';

// WP-020d: the incident list's columns, views, time range, chips, selection, bulk and export.
// Test names cite docs/specs/parity/01-work-items-incidents.md criteria.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ITEM = fakeIncident();
const OTHER = {
  ...fakeIncident(),
  id: '01900000-0000-7000-8000-0000000009f2',
  display_id: 'INC-8',
};
const FIELDS = [
  { name: 'subject', type: 'string', values: [], multiple: false, sortable: true, dimension: null },
  {
    name: 'priority',
    type: 'enum',
    values: ['p1', 'p2', 'p3', 'p4'],
    multiple: false,
    sortable: true,
    dimension: { field: 'priority', kind: 'code', label_prefix: 'priority', reference: null },
  },
  {
    name: 'status_category',
    type: 'enum',
    values: ['open', 'paused', 'resolved', 'closed', 'canceled'],
    multiple: false,
    sortable: false,
    dimension: {
      field: 'status_category',
      kind: 'code',
      label_prefix: 'status_category',
      reference: null,
    },
  },
  {
    name: 'created_at',
    type: 'datetime',
    values: [],
    multiple: false,
    sortable: true,
    dimension: { field: 'created_at', kind: 'datetime', label_prefix: null, reference: null },
  },
  {
    name: 'resolution_due_at',
    type: 'datetime',
    values: [],
    multiple: false,
    sortable: true,
    dimension: null,
  },
  {
    name: 'updated_at',
    type: 'datetime',
    values: [],
    multiple: false,
    sortable: true,
    dimension: null,
  },
];

function routes(extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    'GET /api/v1/incidents': {
      body: {
        items: [ITEM, OTHER].map((i) => ({ ...i, deleted_at: null })),
        has_more: true,
        next_cursor: 'next',
        estimated_total: 120,
        people: ITEM.people,
      },
    },
    'GET /api/v1/incidents/views': {
      body: [
        { view: 'open', count: 120, capped: false },
        { view: 'all', count: 130, capped: false },
      ],
    },
    'GET /api/v1/incidents/list-fields': { body: FIELDS },
    'GET /api/v1/incidents/saved-views': { body: [] },
    'GET /api/v1/incidents/view-filters': {
      body: [
        {
          view: 'open',
          expressible: true,
          filter: { field: 'status_category', op: 'in', value: ['open', 'paused'] },
        },
        { view: 'all', expressible: true, filter: null },
      ],
    },
    'GET /api/v1/incidents/list-settings/open': {
      body: { view_key: 'open', columns: [], sort: null, page_size: 50, version: null },
    },
    ...extra,
  } as Parameters<typeof consoleApi>[0] extends infer A
    ? A extends { routes?: infer R }
      ? R
      : never
    : never;
}

describe('list model', () => {
  it('REQ-INC-109: chips on one field mean either value; fields join with "and"', () => {
    expect(chipsFilter([])).toBeUndefined();
    expect(
      chipsFilter([
        { field: 'priority', value: 'p1', label: '' },
        { field: 'priority', value: 'p2', label: '' },
        { field: 'status_category', value: 'open', label: '' },
      ]),
    ).toEqual({
      and: [
        { field: 'priority', op: 'in', value: ['p1', 'p2'] },
        { field: 'status_category', op: 'eq', value: 'open' },
      ],
    });
  });

  it('REQ-INC-108: presets are relative to the server; a quarter is exact in the user zone', () => {
    expect(rangeFilter({ field: 'created_at', preset: 'this_week' }, 'Asia/Karachi')).toEqual({
      field: 'created_at',
      op: 'this_week',
      value: null,
    });
    expect(rangeFilter({ field: 'updated_at', preset: 'last_7_days' }, 'UTC')).toEqual({
      field: 'updated_at',
      op: 'last_n_days',
      value: 7,
    });
    // 2026-11-15 in Karachi (UTC+5): Q4 starts 2026-10-01 00:00 local = 2026-09-30 19:00 UTC.
    expect(quarterOf(new Date('2026-11-15T12:00:00Z'), 'Asia/Karachi')).toEqual([
      '2026-09-30T19:00:00.000Z',
      '2026-12-31T19:00:00.000Z',
    ]);
    expect(rangeFilter({ field: 'created_at', preset: 'custom' }, 'UTC')).toBeUndefined();
  });

  it('export: a built-in view becomes its filter; one the DSL cannot say is refused', () => {
    const filters = [
      { view: 'open', expressible: true, filter: { field: 'status_category', op: 'eq' } },
      { view: 'updated_by_others', expressible: false, filter: null },
    ];
    const mine = { field: 'priority', op: 'eq' as const, value: 'p1' };
    expect(exportFilter('open', filters, mine)).toEqual({
      and: [{ field: 'status_category', op: 'eq' }, mine],
    });
    expect(exportFilter('updated_by_others', filters, mine)).toBeNull();
    expect(exportFilter(null, filters, mine)).toEqual(mine); // a saved view: its filter is in
  });

  it('REQ-INC-120 AC1: a skipped record says why in words', () => {
    const t = (key: string, params?: Record<string, string | number>) =>
      `${key}${params ? JSON.stringify(params) : ''}`;
    expect(
      skipReason(t, {
        id: 'x',
        display_id: 'INC-1',
        outcome: 'skipped',
        field: 'closure_code',
        code: 'required',
        params: {},
      }),
    ).toBe(
      'incidents.bulk.field_problem{"field":"work_item.field.closure_code","problem":"errors.field.required{}"}',
    );
  });
});

describe('Incident list (WP-020d)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents');
  });
  afterEach(() => {
    restore();
  });

  it('REQ-INC-119 AC2: bulk actions are disabled until something is selected, then "all N"', async () => {
    const fake = api({
      routes: routes({
        'POST /api/v1/incidents/bulk': {
          status: 202,
          body: {
            id: 'job-1',
            action: 'take',
            status: 'queued',
            total: 120,
            processed: 0,
            done_count: 0,
            skipped_count: 0,
            results: [],
            created_at: '2026-10-28T10:00:00Z',
            started_at: null,
            finished_at: null,
          },
        },
      }),
    });
    render(<App />);
    await screen.findByTestId('inc-row-INC-7');
    const take = screen.getByTestId('inc-bulk-take');
    expect((take as HTMLButtonElement).disabled).toBe(true); // no blocking alert, a reason
    expect(screen.getByTestId('inc-selected').textContent).toBe('0 incidents selected');
    const table = screen.getByTestId('inc-table');
    const all = within(table).getAllByRole('checkbox')[0];
    if (all === undefined) throw new Error('no select-all checkbox');
    fireEvent.click(all);
    expect(screen.getByTestId('inc-selected').textContent).toBe('2 incidents selected');
    fireEvent.click(screen.getByTestId('inc-select-all')); // AC1: every match, not the page
    expect(screen.getByTestId('inc-selected').textContent).toBe(
      'All 120 matching incidents are selected.',
    );
    fireEvent.click(screen.getByTestId('inc-bulk-take'));
    fireEvent.click(await screen.findByTestId('inc-bulk-start'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/incidents/bulk')).toHaveLength(1);
    });
    const call = fake.find('POST', '/api/v1/incidents/bulk')[0];
    expect(call?.body).toEqual({ action: 'take', changes: {}, record_ids: [], all_matching: true });
    expect(call?.url.searchParams.get('view')).toBe('open');
  });

  it('REQ-INC-104 AC1/AC3: an added column is saved for this view (and only this view)', async () => {
    const fake = api({
      routes: routes({
        'PUT /api/v1/incidents/list-settings/open': (call: { body: unknown }) => ({
          body: { view_key: 'open', version: 1, ...(call.body as object) },
          headers: { ETag: '"1"' },
        }),
      }),
    });
    render(<App />);
    await screen.findByTestId('inc-row-INC-7');
    fireEvent.click(screen.getByTestId('inc-columns'));
    fireEvent.change(await screen.findByTestId('inc-columns-search'), {
      target: { value: 'created' },
    });
    fireEvent.click(await screen.findByTestId('inc-column-add-created_at'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/incidents/list-settings/open')).toHaveLength(1);
    });
    const saved = fake.find('PUT', '/api/v1/incidents/list-settings/open')[0]?.body as {
      columns: { key: string }[];
      page_size: number;
    };
    expect(saved.columns.map((c) => c.key).at(-1)).toBe('created_at');
    expect(saved.page_size).toBe(50);
    expect(fake.find('PUT', '/api/v1/incidents/list-settings/my_open')).toHaveLength(0);
  });

  it("export: the file gets the view as a filter, the list's columns and its sort", async () => {
    const fake = api({
      routes: routes({
        'POST /api/v1/reports/exports': { status: 202, body: { id: 'e1' } },
        'GET /api/v1/reports/exports': { body: [] },
      }),
    });
    render(<App />);
    await screen.findByTestId('inc-row-INC-7');
    fireEvent.click(screen.getByTestId('inc-export'));
    fireEvent.click(await screen.findByTestId('inc-export-start'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/reports/exports')).toHaveLength(1);
    });
    const body = fake.find('POST', '/api/v1/reports/exports')[0]?.body as {
      content: string;
      definition: { filter: unknown; columns: string[]; sort: unknown };
    };
    expect(body.content).toBe('records');
    expect(body.definition.filter).toEqual({
      field: 'status_category',
      op: 'in',
      value: ['open', 'paused'],
    });
    expect(body.definition.columns[0]).toBe('display_id');
    expect(body.definition.sort).toEqual([{ field: 'updated_at', desc: true }]);
  });

  it('REQ-INC-108: "this week" on created adds one named condition', async () => {
    const fake = api({ routes: routes() });
    render(<App />);
    await screen.findByTestId('inc-row-INC-7');
    const preset = screen.getByTestId('inc-time-preset');
    fireEvent.mouseDown(preset.querySelector('.ant-select-selector') ?? preset);
    fireEvent.click(await screen.findByTitle('This week'));
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents').at(-1);
      expect(JSON.parse(last?.url.searchParams.get('filter') ?? 'null')).toEqual({
        field: 'created_at',
        op: 'this_week',
        value: null,
      });
    });
    expect(screen.getByTestId('inc-time-active').textContent).toBe('Created: This week'); // AC2
  });
});

describe('WP-020f QA', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents');
  });
  afterEach(() => {
    restore();
  });

  const coded = (name: string, values: string[]) => ({
    name,
    type: 'string',
    values,
    multiple: false,
    sortable: true,
    dimension: { field: name, kind: 'admin_code', label_prefix: null, reference: null },
  });

  it('BUG-05: closure code and level are offered by name in search chips', async () => {
    const fake = api({
      routes: routes({
        'GET /api/v1/incidents/list-fields': {
          body: [
            ...FIELDS,
            coded('closure_code', ['fixed', 'confirmed_by_requester']),
            coded('level', ['tier_1', 'tier_2']),
          ],
        },
      }),
    });
    render(<App />);
    await screen.findByTestId('inc-row-INC-7');
    fireEvent.change(screen.getByTestId('inc-search'), { target: { value: 'confirmed' } });
    fireEvent.click(await screen.findByText('Closure code is Confirmed by requester'));
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/incidents').at(-1);
      expect(JSON.parse(last?.url.searchParams.get('filter') ?? 'null')).toMatchObject({
        field: 'closure_code',
        op: 'eq',
        value: 'confirmed_by_requester',
      });
    });
    fireEvent.change(screen.getByTestId('inc-search'), { target: { value: 'tier 2' } });
    expect(await screen.findByText('Level is Tier 2')).toBeDefined();
  });
});

it('BUG-05: in the view builder a coded field is a pick list, never free text', () => {
  const words = {
    field: (name: string) => name,
    choices: (f: { values: string[] }) =>
      f.values.length > 0 ? f.values.map((v) => ({ value: v, label: `named ${v}` })) : undefined,
  } as unknown as ReportWords;
  const [closure, subject] = builderFields(
    [
      {
        name: 'closure_code',
        type: 'string',
        values: ['fixed'],
        multiple: false,
        sortable: true,
        dimension: {
          field: 'closure_code',
          kind: 'admin_code',
          label_prefix: null,
          reference: null,
          bucket: null,
        },
      },
      {
        name: 'subject',
        type: 'string',
        values: [],
        multiple: false,
        sortable: true,
        dimension: null,
      },
    ],
    words,
  );
  expect(closure).toMatchObject({
    type: 'enum',
    choices: [{ value: 'fixed', label: 'named fixed' }],
  });
  expect(subject?.type).toBe('string');
});
