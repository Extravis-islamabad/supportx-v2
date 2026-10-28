import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';

// jsdom has no canvas: charts get a stand-in instance (their options are unit-tested in charts).
// The path is the chart package's own ECharts (the console does not depend on it directly).
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

  it('lists schedules with their next run and last result, and pauses one (REQ-RPT-052, 056)', async () => {
    window.history.pushState({}, '', '/reports');
    const schedule = {
      id: '01900000-0000-7000-8000-00000000s001',
      owner_id: '01900000-0000-7000-8000-000000000101',
      title: 'Weekly open incidents',
      report_ref: 'builtin:incidents_open_by_priority',
      frequency: 'weekly',
      at_time: '07:00:00',
      time_zone: 'Asia/Riyadh',
      start_date: '2026-10-01',
      end_date: null,
      weekdays: [0],
      day_of_month: null,
      recipient_users: [],
      recipient_groups: [],
      format: 'xlsx',
      content: 'summary',
      message: null,
      status: 'active',
      paused_reason: null,
      next_run_at: '2026-11-02T04:00:00Z',
      last_run_at: '2026-10-26T04:00:00Z',
      last_result: 'attachment_too_large',
      last_sent: 0,
      last_failed: 3,
      version: 4,
    };
    const fake = api({
      me: fakeSession({ roles: ['tenant_admin', 'technician'] }),
      routes: routes({
        'GET /api/v1/reports/schedules': { body: { mail_configured: false, items: [schedule] } },
        [`POST /api/v1/reports/schedules/${schedule.id}/pause`]: {
          body: { ...schedule, status: 'paused', version: 5 },
        },
      }),
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('report-schedules'));
    expect(
      await screen.findByText(
        'Outgoing e-mail is not set up, so reports cannot be sent on a schedule. Ask your administrator.',
      ),
    ).toBeDefined();
    const last = await screen.findByTestId(`schedule-last-${schedule.id}`);
    expect(last.textContent).toContain('The file was larger than 10 MB');
    expect(document.body.textContent).not.toMatch(/attachment_too_large|weekly\b/);
    fireEvent.click(screen.getByTestId(`schedule-pause-${schedule.id}`));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/reports/schedules/${schedule.id}/pause`)).toHaveLength(1);
    });
    const call = fake.find('POST', `/api/v1/reports/schedules/${schedule.id}/pause`)[0];
    expect(call?.headers.get('If-Match')).toBe('"4"');
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

  // --- QA WP-035 (~/Desktop/qa-wp035/QA-REPORT.md): one test per finding ------------------------
  describe('QA WP-035', () => {
    const GROUP_A = '01900000-0000-7000-8000-0000000000a1';
    const GROUP_B = '01900000-0000-7000-8000-0000000000b2';
    const ARABIC = fakeSession({ locale: 'ar' });
    const withFilter = (filter: unknown, chart = 'table') =>
      routes({
        'GET /api/v1/reports/library': {
          body: {
            builtin: [{ ...BUILTIN, definition: { ...BUILTIN.definition, filter, chart } }],
            folders: [],
            reports: [],
            favourites: [],
          },
        },
        'GET /api/v1/organization/groups': {
          body: [
            { id: GROUP_A, name: 'Network', version: 1 },
            { id: GROUP_B, name: 'Desktop', version: 1 },
          ],
        },
        'GET /api/v1/reports/entities/incident': {
          body: {
            ...ENTITY,
            fields: [
              ...ENTITY.fields,
              {
                name: 'group_id',
                type: 'uuid',
                values: [],
                multiple: false,
                dimension: {
                  ...PRIORITY_GROUP,
                  field: 'group_id',
                  kind: 'reference',
                  label_prefix: null,
                  reference: 'group',
                },
              },
            ],
          },
        },
      });

    beforeEach(() => {
      window.history.pushState({}, '', '/reports/builtin/incidents_open_by_priority');
    });

    it("BUG-05: lists in the filter words use the language's own joining words, and names, never ids", async () => {
      api({
        me: ARABIC,
        routes: withFilter({
          and: [OPEN, { field: 'group_id', op: 'in', value: [GROUP_A, GROUP_B] }],
        }),
      });
      render(<App />);
      const words = await screen.findByTestId('report-filter-words');
      await waitFor(() => {
        expect(words.textContent).toContain('Network');
      });
      const text = words.textContent;
      expect(text).not.toContain(', ');
      expect(text).toContain(' أو '); // "is one of": A or B
      expect(text).toContain('Desktop');
      expect(text).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}/);
    });

    it('BUG-04: values inside Arabic text are isolated, so numbers keep their place', async () => {
      api({ me: ARABIC, routes: routes() });
      render(<App />);
      const total = await screen.findByTestId('report-total');
      await waitFor(() => {
        expect(total.textContent).toContain('\u206810\u2069');
      });
    });

    it('BUG-02: the chart states its text direction explicitly', async () => {
      api({ me: ARABIC, routes: withFilter(OPEN, 'bar') });
      render(<App />);
      await screen.findByTestId('report-result');
      const chart = await waitFor(() => {
        const found = document.querySelector('[data-testid="report-result"] [role="img"]');
        expect(found).not.toBeNull();
        return found;
      });
      expect(chart?.getAttribute('dir')).toBe('rtl');
    });

    it('BUG-07: every option shows its whole label, in every list of the product', async () => {
      api({ me: fakeSession(), routes: routes() });
      render(<App />);
      await screen.findByTestId('report-table');
      const chartType = screen.getByTestId('report-chart-type');
      fireEvent.mouseDown(chartType.querySelector('.ant-select-selector') ?? chartType);
      const option = await screen.findByTitle('Stacked bar');
      const content = option.querySelector('.ant-select-item-option-content') ?? option;
      // One rule for the whole product (AppearanceProvider), not a prop per list.
      expect(getComputedStyle(content).whiteSpace).toBe('normal');
      expect(getComputedStyle(content).textOverflow).toBe('clip');
    });

    it('BUG-08: a changed built-in report says so, with Reset and Save as my report', async () => {
      api({ me: fakeSession(), routes: routes() });
      render(<App />);
      await screen.findByTestId('report-table');
      expect(screen.queryByTestId('report-modified')).toBeNull();
      const grouping = screen.getByTestId('report-group');
      fireEvent.mouseDown(grouping.querySelector('.ant-select-selector') ?? grouping);
      const options = await screen.findAllByTitle('State');
      fireEvent.click(options[options.length - 1] ?? grouping);
      const notice = await screen.findByTestId('report-modified');
      expect(notice.textContent).toContain('Changed from Open incidents by priority');
      expect(within(notice).getByRole('button', { name: 'Save as my report' })).toBeDefined();
      fireEvent.click(within(notice).getByRole('button', { name: 'Reset' }));
      await waitFor(() => {
        expect(screen.queryByTestId('report-modified')).toBeNull();
      });
    });
  });

  // --- D-105 (WP-029-FIX rules) on report forms: refusals at the form, failures as a toast ----
  describe('D-105 on report forms', () => {
    const toasts = () =>
      [...document.querySelectorAll('.ant-notification-notice')].map((n) => n.textContent);

    beforeEach(() => {
      window.history.pushState({}, '', '/reports/builtin/incidents_open_by_priority');
    });

    async function exportWith(status: number, body: unknown): Promise<void> {
      api({
        me: fakeSession(),
        routes: routes({ 'POST /api/v1/reports/exports': { status, body } }),
      });
      render(<App />);
      await screen.findByTestId('report-table');
      fireEvent.click(screen.getByTestId('report-export'));
      fireEvent.click(await screen.findByRole('button', { name: 'Export' }));
    }

    it('a refused export shows once, in its dialog, with no toast', async () => {
      await exportWith(429, problem(429, 'report_queue_full', { params: { seconds: 30 } }));
      const shown = await screen.findByTestId('form-problem');
      expect(within(screen.getByRole('dialog')).getByTestId('form-problem')).toBe(shown);
      expect(shown.textContent).not.toMatch(/\{\{|report_queue_full/);
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(toasts()).toEqual([]);
    });

    it('a failed export (500) is an error toast with its reference', async () => {
      await exportWith(500, problem(500, 'internal_error'));
      await waitFor(() => {
        expect(toasts()).toHaveLength(1);
      });
      expect(toasts()[0]).toContain('Copy reference');
      expect(screen.queryByTestId('form-problem')).toBeNull();
    });

    it('a report that cannot run (500) is an error toast; a refused one (time limit) stays on the page', async () => {
      api({
        me: fakeSession(),
        routes: routes({
          'POST /api/v1/reports/run': { status: 500, body: problem(500, 'internal_error') },
        }),
      });
      render(<App />);
      await waitFor(() => {
        expect(toasts()).toHaveLength(1);
      });
      expect(toasts()[0]).toContain('Copy reference');
      expect(screen.queryByTestId('report-error')).toBeNull();
    });

    it('a refused run (time limit) is a notice on the page, never a toast', async () => {
      api({
        me: fakeSession(),
        routes: routes({
          'POST /api/v1/reports/run': {
            status: 422,
            body: problem(422, 'report_timeout', { params: { seconds: 30 } }),
          },
        }),
      });
      render(<App />);
      const shown = await screen.findByTestId('report-error');
      expect(shown.textContent).not.toMatch(/\{\{|report_timeout/);
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(toasts()).toEqual([]);
    });

    it('a refused "save as my report" shows at its dialog', async () => {
      api({
        me: fakeSession(),
        routes: routes({
          'POST /api/v1/reports': {
            status: 422,
            body: problem(422, 'validation_failed', {
              errors: [
                {
                  field: 'body.name',
                  code: 'too_long',
                  message_key: 'errors.field.too_long',
                  params: { max: 200 },
                },
              ],
            }),
          },
        }),
      });
      render(<App />);
      await screen.findByTestId('report-table');
      fireEvent.click(screen.getByTestId('report-save-copy'));
      fireEvent.click(await screen.findByRole('button', { name: 'Save' }));
      expect(await within(screen.getByRole('dialog')).findByTestId('form-problem')).toBeDefined();
      expect(toasts()).toEqual([]);
    });
  });
});
