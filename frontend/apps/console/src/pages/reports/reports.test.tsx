import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const OPEN = { field: 'status_category', op: 'in', value: ['open', 'paused'] };
const BUILTIN = {
  code: 'incidents_open_by_priority',
  folder: 'incidents',
  definition: {
    schema_version: 1,
    entity: 'incident',
    filter: OPEN,
    group_by: [{ field: 'priority', bucket: null }],
    measures: ['count'],
    order: 'value_desc',
    limit: null,
    chart: 'table',
    percent: false,
  },
};
const PRIORITY_GROUP = {
  field: 'priority',
  kind: 'code',
  label_prefix: 'priority',
  reference: null,
  bucket: null,
};
const RESULT = {
  entity: 'incident',
  list_path: 'incidents',
  as_of: '2026-10-27T10:00:00Z',
  time_zone: 'UTC',
  groups: [PRIORITY_GROUP],
  measures: [{ code: 'count', unit: 'count', better: 'neutral' }],
  rows: [
    {
      keys: ['p1'],
      values: [8],
      drill: { and: [OPEN, { field: 'priority', op: 'eq', value: 'p1' }] },
    },
    {
      keys: ['p3'],
      values: [2],
      drill: { and: [OPEN, { field: 'priority', op: 'eq', value: 'p3' }] },
    },
  ],
  totals: [10],
  truncated: false,
  drill_all: OPEN,
};
const ENTITY = {
  entity: 'incident',
  list_path: 'incidents',
  fields: [
    {
      name: 'priority',
      type: 'enum',
      values: ['p1', 'p2', 'p3', 'p4'],
      multiple: false,
      dimension: PRIORITY_GROUP,
    },
    {
      name: 'status_category',
      type: 'enum',
      values: ['open', 'paused', 'resolved', 'closed', 'canceled'],
      multiple: false,
      dimension: { ...PRIORITY_GROUP, field: 'status_category', label_prefix: 'status_category' },
    },
  ],
  measures: [{ code: 'count', unit: 'count', better: 'neutral' }],
};
const EMPTY_LIST = { items: [], has_more: false, next_cursor: null };

function routes(extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/reports/library': {
      body: { builtin: [BUILTIN], folders: [], reports: [], favourites: [] },
    },
    'GET /api/v1/reports/entities/incident': { body: ENTITY },
    'POST /api/v1/reports/run': { body: RESULT },
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

describe('Reports', () => {
  afterEach(() => {
    restore();
  });

  it('lists built-in reports by name in their folder and stars one (REQ-RPT-045)', async () => {
    window.history.pushState({}, '', '/reports');
    const fake = api({
      me: fakeSession(),
      routes: routes({
        'PUT /api/v1/reports/favourites/builtin%3Aincidents_open_by_priority': { status: 204 },
      }),
    });
    render(<App />);
    const link = await screen.findByTestId('reports-open-builtin:incidents_open_by_priority');
    expect(link.textContent).toBe('Open incidents by priority');
    const section = screen.getByTestId('reports-section');
    expect(section.querySelector('.ant-card-head-title')?.textContent).toBe('Incidents');
    expect(document.body.textContent).not.toMatch(/incidents_open_by_priority/);
    // No folder management without reports.manage_folders.
    expect(screen.queryByTestId('reports-new-folder')).toBeNull();
    fireEvent.click(screen.getByTestId('reports-star-builtin:incidents_open_by_priority'));
    await waitFor(() => {
      expect(
        fake.find('PUT', '/api/v1/reports/favourites/builtin%3Aincidents_open_by_priority'),
      ).toHaveLength(1);
    });
  });

  describe('viewer', () => {
    beforeEach(() => {
      window.history.pushState({}, '', '/reports/builtin/incidents_open_by_priority');
    });

    it('shows labels, the filter in words and the total, and drills down to the records (REQ-RPT-037, 050)', async () => {
      const incident = fakeIncident({ display_id: 'INC-8', subject: 'Printer down' });
      const fake = api({
        me: fakeSession(),
        routes: routes({
          'GET /api/v1/incidents': {
            body: { ...EMPTY_LIST, items: [incident], estimated_total: 8, people: [] },
          },
        }),
      });
      render(<App />);
      expect((await screen.findByTestId('report-title')).textContent).toBe(
        'Open incidents by priority',
      );
      const table = await screen.findByTestId('report-table');
      expect(within(table).getByText('P1 – Critical')).toBeDefined();
      expect(table.textContent).not.toMatch(/\bp1\b|\bp3\b/);
      expect((await screen.findByTestId('report-total')).textContent).toBe('Incidents: 10');
      expect(screen.getByTestId('report-filter-words').textContent).toContain('State is one of');
      const run = fake.find('POST', '/api/v1/reports/run')[0];
      expect((run?.body as { definition: { entity: string } }).definition.entity).toBe('incident');

      fireEvent.click(within(table).getByText('P1 – Critical'));
      expect(await screen.findByText('Printer down')).toBeDefined();
      const drill = fake.find('GET', '/api/v1/incidents').at(-1);
      expect(JSON.parse(drill?.url.searchParams.get('filter') ?? 'null')).toEqual(
        RESULT.rows[0]?.drill,
      );
      expect(screen.getByTestId('report-drill-count').textContent).toBe('Records: 8');
    });

    it('exports to a file in the background and lists my exports (REQ-RPT-058)', async () => {
      const ready = {
        id: '01900000-0000-7000-8000-00000000e001',
        title: 'Open incidents by priority',
        format: 'xlsx',
        content: 'summary',
        status: 'ready',
        problem: null,
        row_count: 2,
        size_bytes: 1200,
        created_at: '2026-10-28T09:00:00Z',
        expires_at: '2026-11-04T09:00:00Z',
      };
      const failed = {
        ...ready,
        id: '01900000-0000-7000-8000-00000000e002',
        format: 'pdf',
        status: 'failed',
        problem: 'pdf_not_available',
        row_count: null,
      };
      const fake = api({
        me: fakeSession(),
        routes: routes({
          'POST /api/v1/reports/exports': { status: 202, body: { ...ready, status: 'running' } },
          'GET /api/v1/reports/exports': { body: [ready, failed] },
        }),
      });
      render(<App />);
      await screen.findByTestId('report-table');
      fireEvent.click(screen.getByTestId('report-export'));
      fireEvent.click(await screen.findByText('CSV'));
      fireEvent.click(screen.getByText('Every record behind it'));
      fireEvent.click(screen.getByRole('button', { name: 'Export' }));
      await waitFor(() => {
        expect(fake.find('POST', '/api/v1/reports/exports')).toHaveLength(1);
      });
      const body = fake.find('POST', '/api/v1/reports/exports')[0]?.body as {
        format: string;
        content: string;
        title: string;
        language: string;
      };
      expect(body).toMatchObject({
        format: 'csv',
        content: 'records',
        title: 'Open incidents by priority',
        language: 'en',
      });
      fireEvent.click(screen.getByTestId('report-my-exports'));
      const link = await screen.findByTestId(`report-export-download-${ready.id}`);
      expect(link.getAttribute('href')).toBe(`/api/v1/reports/exports/${ready.id}/file`);
      expect(screen.getByTestId(`report-export-status-${failed.id}`).textContent).toBe('Failed');
      expect(screen.getByText('PDF export is not available on this server.')).toBeDefined();
      expect(document.body.textContent).not.toMatch(/pdf_not_available/);
    });

    it('does not run while a condition has no value, and says why (REQ-RPT-029 AC2)', async () => {
      const fake = api({ me: fakeSession(), routes: routes() });
      render(<App />);
      await screen.findByTestId('report-table');
      const before = fake.find('POST', '/api/v1/reports/run').length;
      fireEvent.click(screen.getByTestId('report-filter-add'));
      expect(await screen.findByTestId('report-cannot-run')).toBeDefined();
      expect(screen.getByTestId('report-save-copy').hasAttribute('disabled')).toBe(true);
      await new Promise((resolve) => setTimeout(resolve, 600));
      expect(fake.find('POST', '/api/v1/reports/run').length).toBe(before);
    });
  });
});
