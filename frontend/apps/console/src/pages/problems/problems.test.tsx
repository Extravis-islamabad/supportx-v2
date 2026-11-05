import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-044a s5: problems in the console: the list, creating one from an incident (prefilled, with
// similar problems), and the record with the guided steps and investigators. WP-044b s1: the
// analysis and evidence tabs.

const PRB_ID = '01a1a2b3-0000-7000-8000-00000000e001';
const INC_ID = '01a1a2b3-0000-7000-8000-00000000c101';
const TEMPLATE_ID = '01a1a2b3-0000-7000-8000-00000000f001';
const TECH = '01a1a2b3-0000-7000-8000-00000000b101';

const record = fakeIncident({
  id: PRB_ID,
  type: 'problem',
  display_id: 'PRB-7',
  subject: 'Mail relay drops messages',
  status: 'gathering_facts',
  lifecycle: 'guided_analysis',
  actions: [
    {
      action: 'analyse',
      allowed: true,
      reason: null,
      reason_mode: 'none',
      reason_list: null,
    },
  ],
});

const template = {
  id: TEMPLATE_ID,
  code: 'standard',
  labels: null,
  description: null,
  group_name: null,
  is_default: true,
  for_requesters: false,
  disabled: false,
  copied_from_id: null,
  fields: {},
  custom_fields: {},
  defaults: {},
  lifecycle: 'standard',
  version: 1,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/problems': {
        body: { items: [record], next_cursor: null, has_more: false, people: {} },
      },
      'GET /api/v1/problems/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/problems/templates': { body: [template] },
      'GET /api/v1/problems/similar': { body: [] },
      [`GET /api/v1/problems/${PRB_ID}`]: { body: record },
      [`GET /api/v1/problems/${PRB_ID}/links`]: { body: [] },
      [`GET /api/v1/problems/${PRB_ID}/investigators`]: {
        body: {
          user_ids: [TECH],
          people: { [TECH]: { display_name: 'Nadia Network', email: 'nadia@example.com' } },
        },
      },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: problems', () => {
  it('lists problems with a way to create one', async () => {
    window.history.pushState({}, '', '/problems');
    api();
    render(<App />);
    const row = (await screen.findByTestId('prb-row-PRB-7')).closest('tr');
    expect(within(row as HTMLElement).getByText('Mail relay drops messages')).toBeDefined();
    expect(screen.getByTestId('prb-new')).toBeDefined();
  });

  it('creates one from an incident: prefilled, similar problems shown, linked on save', async () => {
    window.history.pushState({}, '', `/problems/new?incident=${INC_ID}`);
    const fake = api({
      'GET /api/v1/problems/prefill': {
        body: {
          subject: 'Mail is down',
          description: null,
          impact: null,
          urgency: null,
          site_id: null,
          category_id: null,
          requester_id: TECH,
          problem_type: 'reactive',
          source_incident_id: INC_ID,
        },
      },
      'GET /api/v1/problems/similar': {
        body: [
          {
            id: PRB_ID,
            display_id: 'PRB-7',
            subject: 'Mail relay drops messages',
            status: 'investigating',
            status_category: 'open',
          },
        ],
      },
      'POST /api/v1/problems/from-incidents': {
        status: 201,
        body: { problem: record, bulk_jobs: [] },
      },
    });
    render(<App />);
    const subject = await screen.findByTestId('prb-subject');
    expect((subject as HTMLInputElement).value).toBe('Mail is down');
    expect(await screen.findByTestId('prb-similar-PRB-7')).toBeDefined();
    fireEvent.click(screen.getByTestId('prb-create'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/problems/from-incidents')).toHaveLength(1);
    });
    const sent = fake.find('POST', '/api/v1/problems/from-incidents')[0]?.body as {
      main_incident_id: string;
      problem: { subject: string; requester_id: string; template_id: string };
    };
    expect(sent.main_incident_id).toBe(INC_ID);
    expect(sent.problem.subject).toBe('Mail is down');
    expect(sent.problem.requester_id).toBe(TECH); // reported by: the creator
    expect(sent.problem.template_id).toBe(TEMPLATE_ID); // the default template first
    await screen.findByTestId('prb-record');
  });

  it('shows the guided steps, the next move and the investigators', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    api();
    render(<App />);
    const steps = await screen.findByTestId('prb-guided-steps');
    expect(within(steps).getByText('Gathering facts')).toBeDefined();
    expect(within(steps).getByText('In review')).toBeDefined();
    expect(await screen.findByRole('button', { name: 'Start the why-analysis' })).toBeDefined();
    expect(await screen.findByText('Nadia Network')).toBeDefined();
  });

  it('analysis: impact figures, a locked root cause, and symptoms edited in place', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    const hidden = {
      ...record,
      root_cause: null,
      root_cause_hidden: true,
      symptoms: '<p>Mail stalls at 9.</p>',
      operations: [
        ...record.operations,
        { action: 'edit_analysis', allowed: true, reason: null, reason_mode: 'none' as const },
      ],
    };
    const fake = api({
      [`GET /api/v1/problems/${PRB_ID}`]: { body: hidden },
      [`GET /api/v1/problems/${PRB_ID}/impact`]: {
        body: {
          incidents: 4,
          open_incidents: 3,
          by_priority: [{ priority: 'p2', count: 4 }],
          by_site: [{ site_id: null, count: 4 }],
          people: 2,
          minutes: 90,
          partial: true,
        },
      },
      [`PATCH /api/v1/problems/${PRB_ID}`]: {
        body: { ...hidden, symptoms: '<p>Mail stalls at 9 and 2.</p>', version: 2 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('prb-tab-analysis'));
    const impact = await screen.findByTestId('prb-impact');
    expect(
      within(impact).getByText('4', { selector: '.ant-statistic-content-value-int' }),
    ).toBeDefined();
    expect(within(impact).getByTestId('prb-impact-partial')).toBeDefined();
    expect(within(impact).getByTestId('prb-impact-hours').textContent).toContain('1.5'); // 90 min
    // The root cause is locked, never shown as empty, and offers no edit.
    const cause = screen.getByTestId('prb-root-cause');
    expect(within(cause).getByTestId('prb-root-cause-hidden')).toBeDefined();
    expect(within(cause).queryByRole('button', { name: /Edit/ })).toBeNull();
    expect(within(screen.getByTestId('prb-symptoms')).getByText('Mail stalls at 9.')).toBeDefined();
    fireEvent.click(screen.getByTestId('prb-symptoms-edit'));
    expect(await screen.findByTestId('prb-symptoms-editor')).toBeDefined();
    fireEvent.click(screen.getByTestId('prb-symptoms-save'));
    await waitFor(() => {
      const patch = fake.calls.find((c) => c.method === 'PATCH');
      expect(patch?.headers.get('If-Match')).toBe('"1"');
      expect(Object.keys(patch?.body as object)).toContain('symptoms');
      expect(Object.keys(patch?.body as object)).not.toContain('root_cause');
    });
  });

  it('evidence: the caused incidents in report order, and what is not there yet', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    api({
      [`GET /api/v1/problems/${PRB_ID}/evidence`]: {
        body: {
          incidents: [
            {
              id: INC_ID,
              display_id: 'INC-41',
              subject: 'Mail slow',
              priority: 'p3',
              status: 'resolved',
              status_category: 'resolved',
              site_id: null,
              reported_at: '2026-11-01T08:00:00Z',
              resolved_at: '2026-11-01T10:00:00Z',
            },
          ],
          left_out: true,
          pending_sources: ['changes', 'releases', 'same_items'],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('prb-tab-evidence'));
    expect(await screen.findByTestId('prb-evidence-INC-41')).toBeDefined();
    expect(screen.getByTestId('prb-evidence-pending').textContent).toContain(
      'Changes, Releases, and Other problems on the same items',
    );
    expect(screen.getByTestId('prb-evidence-left-out')).toBeDefined();
  });
});
