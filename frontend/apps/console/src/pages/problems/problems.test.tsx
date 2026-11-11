import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { clickAction } from '../../test/actions';
import { consoleApi, problem } from '../../test/api';

// WP-044a s5: problems in the console: the list, creating one from an incident (prefilled, with
// similar problems), and the record with the guided steps and investigators. WP-044b s1: the
// analysis and evidence tabs.

// jsdom has no canvas: the impact trend gets a stand-in chart (its options are tested in charts).
vi.mock('../../../../../packages/charts/node_modules/echarts/core', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  init: () => ({
    on: () => undefined,
    setOption: () => undefined,
    resize: () => undefined,
    dispose: () => undefined,
  }),
}));

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
      'GET /api/v1/problem-repeats/hits': { body: [] },
      'GET /api/v1/problems/views': {
        body: [
          { view: 'all_open', count: 1, capped: false },
          { view: 'known_errors', count: 0, capped: false },
          { view: 'accepted_due_review', count: 0, capped: false },
        ],
      },
      'GET /api/v1/problems/templates': { body: [template] },
      'GET /api/v1/problems/similar': { body: [] },
      'POST /api/v1/problems/from-incidents/preview': { body: { already_caused: [] } },
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
  it('WP-044c S1: the views with their counts, and a search for words or a PRB number', async () => {
    window.history.pushState({}, '', '/problems');
    const fake = api();
    render(<App />);
    await screen.findByTestId('prb-row-PRB-7');
    // QA 2026-11-10: the list asks for the view the selector shows, from its first request on
    // (no view meant every problem, a closed one under "All open (7)").
    expect(
      fake.find('GET', '/api/v1/problems').map((c) => c.url.searchParams.get('view')),
    ).not.toContain(null);
    expect(fake.find('GET', '/api/v1/problems')[0]?.url.searchParams.get('view')).toBe('all_open');
    const selector = screen.getByTestId('prb-view').querySelector('.ant-select-selector');
    if (selector === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(selector);
    fireEvent.click(await screen.findByText('Known errors (0)'));
    await waitFor(() => {
      expect(
        fake
          .find('GET', '/api/v1/problems')
          .some((c) => c.url.searchParams.get('view') === 'known_errors'),
      ).toBe(true);
    });
    fireEvent.change(screen.getByTestId('prb-search'), { target: { value: 'PRB-7' } });
    await waitFor(() => {
      const sent = fake
        .find('GET', '/api/v1/problems')
        .map((c) => c.url.searchParams.get('filter'))
        .filter((f): f is string => f !== null);
      expect(sent.some((f) => f.includes('"display_number"') && f.includes('7'))).toBe(true);
    });
  });

  it('WP-044c S1: the ID and subject stay in view and a long subject ends in an ellipsis', async () => {
    window.history.pushState({}, '', '/problems');
    api();
    render(<App />);
    const row = (await screen.findByTestId('prb-row-PRB-7')).closest('tr') as HTMLElement;
    const cells = row.querySelectorAll('td');
    expect(cells[0]?.className).toContain('ant-table-cell-fix-left');
    expect(cells[1]?.className).toContain('ant-table-cell-fix-left');
    expect(cells[1]?.className).toContain('ant-table-cell-ellipsis');
  });

  it('WP-044c D16: a set of repeated incidents, dismissed or turned into a problem', async () => {
    const HIT = {
      id: '01a1a2b3-0000-7000-8000-0000000aa001',
      rule_id: '01a1a2b3-0000-7000-8000-0000000aa002',
      category_id: null,
      site_id: null,
      group_id: null,
      incident_count: 12,
      first_at: '2026-11-06T08:00:00Z',
      last_at: '2026-11-06T10:00:00Z',
      version: 1,
    };
    window.history.pushState({}, '', '/problems');
    const fake = api({
      'GET /api/v1/problem-repeats/hits': { body: [HIT] },
      [`POST /api/v1/problem-repeats/hits/${HIT.id}/handle`]: { body: { ...HIT, version: 2 } },
    });
    render(<App />);
    const card = await screen.findByTestId('prb-repeats');
    expect(card.textContent).toContain('12 similar incidents');
    fireEvent.click(within(card).getByTestId(`prb-repeat-dismiss-${HIT.id}`));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/problem-repeats/hits/${HIT.id}/handle`)).toHaveLength(1);
    });
    expect(fake.find('POST', `/api/v1/problem-repeats/hits/${HIT.id}/handle`)[0]?.body).toEqual({
      outcome: 'dismissed',
      problem_id: null,
    });
    fireEvent.click(within(card).getByTestId(`prb-repeat-create-${HIT.id}`));
    await waitFor(() => {
      expect(window.location.search).toBe(`?repeat=${HIT.id}`);
    });
  });

  it('lists problems with a way to create one', async () => {
    window.history.pushState({}, '', '/problems');
    api();
    render(<App />);
    const row = (await screen.findByTestId('prb-row-PRB-7')).closest('tr');
    expect(within(row as HTMLElement).getByText('Mail relay drops messages')).toBeDefined();
    expect(screen.getByTestId('prb-new')).toBeDefined();
    // QA10V-17: a defaulted priority is an icon with its name, never a bare "*".
    const priority = within(row as HTMLElement).getByTestId('inc-priority');
    expect(priority.textContent).not.toContain('*');
    expect(
      within(priority).getByRole('img', { name: 'Default (impact and urgency unknown)' }),
    ).toBeDefined();
  });

  it('Haider 2026-11-10: the list is the list template; a column resized by keyboard is kept for this view', async () => {
    window.history.pushState({}, '', '/problems');
    const fake = api({
      'GET /api/v1/problems/list-settings/all_open': {
        body: { view_key: 'all_open', columns: [], sort: null, page_size: 50, version: null },
      },
      'PUT /api/v1/problems/list-settings/all_open': (call: { body: unknown }) => ({
        body: { view_key: 'all_open', version: 1, ...(call.body as object) },
        headers: { ETag: '"1"' },
      }),
    });
    render(<App />);
    await screen.findByTestId('prb-row-PRB-7');
    expect(screen.getByTestId('prb-filterbar')).toBeDefined(); // the one toolbar
    const [subject] = screen.getAllByRole('separator', { name: /Subject/ });
    if (subject === undefined) throw new Error('no resize handle on the subject');
    // Each step saves once; the next starts from what was saved.
    for (let i = 1; i <= 3; i += 1) {
      fireEvent.keyDown(subject, { key: 'ArrowLeft', shiftKey: true });
      await waitFor(() => {
        expect(fake.find('PUT', '/api/v1/problems/list-settings/all_open')).toHaveLength(i);
      });
    }
    const last = fake.find('PUT', '/api/v1/problems/list-settings/all_open').at(-1)?.body as {
      columns: { key: string; width: number | null }[];
    };
    // Never narrower than the subject's minimum; saved under this list's own settings.
    expect(last.columns.find((c) => c.key === 'subject')?.width).toBe(180);
    expect(fake.find('PUT', '/api/v1/incidents/list-settings/all_open')).toHaveLength(0);
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
    // Create is always there, as on the incident form (QA9-F-10): an empty subject is said on
    // the field and nothing is sent.
    fireEvent.change(subject, { target: { value: '' } });
    fireEvent.click(screen.getByTestId('prb-create'));
    expect(await screen.findByText('This field is required.')).toBeDefined();
    expect(fake.find('POST', '/api/v1/problems/from-incidents')).toHaveLength(0);
    fireEvent.change(subject, { target: { value: 'Mail is down' } });
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

  it('QA10-P1-02: from one incident another problem causes, the move is offered and sent', async () => {
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
      'POST /api/v1/problems/from-incidents/preview': {
        body: { already_caused: [{ incident_id: INC_ID, problem_display_id: 'PRB-4' }] },
      },
      'POST /api/v1/problems/from-incidents': {
        status: 201,
        body: { problem: record, bulk_jobs: [] },
      },
    });
    render(<App />);
    // Wait on state, not time (lane B's report, merge-group run 43023204885): the prefill has
    // filled the form, and the tick is in the form, before Create is pressed.
    await screen.findByDisplayValue('Mail is down');
    const caused = await screen.findByTestId('prb-already-caused');
    const move = within(caused).getByRole('checkbox');
    fireEvent.click(move);
    await waitFor(() => {
      expect((move as HTMLInputElement).checked).toBe(true);
    });
    fireEvent.click(screen.getByTestId('prb-create'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/problems/from-incidents')).toHaveLength(1);
    });
    const sent = fake.find('POST', '/api/v1/problems/from-incidents')[0]?.body as {
      move_incident_ids: string[];
    };
    expect(sent.move_incident_ids).toEqual([INC_ID]);
  });

  it("WP-044c S1: a problem gets its group and owner in the incident's assign dialog", async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    const fake = api({
      'GET /api/v1/problems/assignees': {
        body: [
          { id: TECH, display_name: 'Nadia Network', email: 'nadia@example.com', open_count: 0 },
        ],
      },
      'GET /api/v1/organization/groups': { body: [] },
    });
    render(<App />);
    await screen.findByTestId('prb-record');
    await clickAction('prb-op-assign', 'prb-actions');
    expect(await screen.findByTestId('inc-assign-technician')).toBeDefined();
    // The owners offered are those who may work problems, not incidents.
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/problems/assignees').length).toBeGreaterThan(0);
    });
    expect(fake.find('GET', '/api/v1/incidents/assignees')).toHaveLength(0);
  });

  it('QA10V-09: the panel lists filled fields only, the empty ones behind Add details', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    api(); // no problem type, no owner, no target date
    render(<App />);
    const panel = await screen.findByTestId('prb-properties');
    expect(panel.textContent).not.toContain('Problem type');
    expect(screen.getByTestId('prb-properties-add').textContent).toMatch(/Add details \(\d\)/);
  });

  it('WP-044c S1: a problem prints as a document', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    api();
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined);
    render(<App />);
    await screen.findByTestId('prb-record');
    await clickAction('prb-print', 'prb-actions');
    expect(print).toHaveBeenCalledTimes(1);
  });

  it('QA10-P1-04: a move refused for an empty field names the field, never a vague toast', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    api({
      [`POST /api/v1/problems/${PRB_ID}/actions/analyse`]: {
        status: 422,
        body: problem(422, 'closure_rules', {
          errors: [
            {
              field: 'body.root_cause',
              code: 'required_to_resolve',
              message_key: 'errors.field.required_to_resolve',
              params: {},
            },
          ],
        }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Start the why-analysis' }));
    expect(await screen.findByText('Fill these on the record first: Root cause.')).toBeDefined();
    expect(screen.queryByText('Some things are needed before this can be done.')).toBeNull();
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
      review_required: true,
      symptoms: '<p>Mail stalls at 9.</p>',
      analysis_changes: [
        { field: 'symptoms', changed_by: TECH, changed_at: '2026-11-04T09:00:00Z' },
      ],
      people: {
        ...record.people,
        [TECH]: { display_name: 'Nadia Network', email: 'nadia@example.com' },
      },
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
          open_seconds: 7200,
          weekly: [
            { week_start: '2026-10-26T00:00:00Z', count: 1 },
            { week_start: '2026-11-02T00:00:00Z', count: 3 },
          ],
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
    expect(within(impact).getByTestId('prb-impact-open-hours').textContent).toContain('2');
    expect(within(impact).getByTestId('prb-impact-trend')).toBeDefined();
    expect(within(impact).getByTestId('prb-impact-hours').textContent).toContain('1.5'); // 90 min
    // The root cause is locked, never shown as empty, and offers no edit.
    const cause = screen.getByTestId('prb-root-cause');
    expect(within(cause).getByTestId('prb-root-cause-hidden')).toBeDefined();
    expect(within(cause).queryByRole('button', { name: /Edit/ })).toBeNull();
    expect(within(screen.getByTestId('prb-symptoms')).getByText('Mail stalls at 9.')).toBeDefined();
    expect(screen.getByTestId('prb-review-required')).toBeDefined(); // no summary yet
    expect(screen.getByTestId('prb-symptoms-changed').textContent).toContain('Nadia Network');
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

  it('links: unlink a caused incident; a merged problem says where it went, with undo', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    const SURVIVOR = '01a1a2b3-0000-7000-8000-00000000e002';
    const merged = {
      ...record,
      status: 'merged',
      status_category: 'closed' as const,
      operations: [{ action: 'edit', allowed: true, reason: null, reason_mode: 'none' as const }],
    };
    const link = (over: Record<string, unknown>) => ({
      id: crypto.randomUUID(),
      kind: 'caused_by',
      other_type: 'incident',
      comment: null,
      version: 1,
      created_at: '2026-11-04T09:00:00Z',
      ...over,
    });
    const fake = api({
      [`GET /api/v1/problems/${PRB_ID}`]: { body: merged },
      [`GET /api/v1/problems/${PRB_ID}/links`]: {
        body: [
          link({
            relation: 'causes',
            other_id: INC_ID,
            other_display_id: 'INC-41',
            other_subject: 'Mail slow',
          }),
          link({
            kind: 'merged_into',
            relation: 'merged_into',
            other_type: 'problem',
            other_id: SURVIVOR,
            other_display_id: 'PRB-9',
            other_subject: 'Mail relay drops messages',
          }),
        ],
      },
      [`DELETE /api/v1/problems/${PRB_ID}/incidents/${INC_ID}`]: { body: { unlinked: true } },
      [`POST /api/v1/problems/${PRB_ID}/undo-merge`]: {
        body: {
          id: PRB_ID,
          status: 'gathering_facts',
          version: 2,
          moved_incident_ids: [],
          stayed_incident_ids: [],
        },
      },
    });
    render(<App />);
    const banner = await screen.findByTestId('prb-merged');
    expect(await within(banner).findByText('PRB-9')).toBeDefined();
    fireEvent.click(within(banner).getByTestId('prb-undo-merge'));
    fireEvent.click(await screen.findByTestId('prb-unlink-INC-41'));
    await waitFor(() => {
      const undo = fake.calls.find((c) => c.path.endsWith('/undo-merge'));
      expect(undo?.headers.get('If-Match')).toBe('"1"');
      expect(fake.calls.some((c) => c.method === 'DELETE' && c.path.endsWith(INC_ID))).toBe(true);
    });
  });

  it('known error: the marker, one action that flips in place, and removing asks a reason', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    const marked = {
      ...record,
      known_error_at: '2026-11-04T09:00:00Z',
      known_error_retired_at: null,
      operations: [
        ...record.operations,
        { action: 'mark_known_error', allowed: true, reason: null, reason_mode: 'none' as const },
      ],
    };
    const fake = api({
      [`GET /api/v1/problems/${PRB_ID}`]: { body: marked },
      [`POST /api/v1/problems/${PRB_ID}/known-error/remove`]: {
        body: { ...marked, known_error_at: null, version: 2 },
      },
    });
    render(<App />);
    expect(await screen.findByTestId('prb-known-error')).toBeDefined();
    // Past the bar's three buttons, it waits in the menu, in the same place either way.
    fireEvent.click(await screen.findByTestId('prb-actions-more'));
    fireEvent.click(await screen.findByText('Remove known error'));
    const ok = await screen.findByTestId('prb-known-error-ok');
    expect(ok.hasAttribute('disabled')).toBe(true); // a reason first
    fireEvent.change(screen.getByTestId('prb-known-error-text'), {
      target: { value: 'Not reproducible' },
    });
    fireEvent.click(ok);
    await waitFor(() => {
      const call = fake.calls.find((c) => c.path.endsWith('/known-error/remove'));
      expect(call?.body).toEqual({ reason: 'Not reproducible' });
    });
  });

  it('the known error database lists what matches, retired ones marked', async () => {
    window.history.pushState({}, '', '/problems/known-errors');
    api({
      'GET /api/v1/problems/known-errors': {
        body: [
          {
            id: PRB_ID,
            display_id: 'PRB-7',
            subject: 'Mail relay drops messages',
            status: 'resolved',
            symptoms: '<p>Error 4.4.2</p>',
            workaround: '<p>Restart the relay.</p>',
            known_error_at: '2026-11-01T08:00:00Z',
            retired_at: '2026-11-03T08:00:00Z',
            incidents: 4,
          },
        ],
      },
    });
    render(<App />);
    const row = await screen.findByTestId('known-error-PRB-7');
    expect(row.textContent).toContain('Mail relay drops messages');
    expect(screen.getByText('Error 4.4.2')).toBeDefined();
    expect(screen.getByText('Retired known error')).toBeDefined();
  });

  it('approvals: the named approver approves through the decision dialog', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    const APPROVAL = '01a1a2b3-0000-7000-8000-00000000a001';
    const fake = api({
      [`GET /api/v1/problems/${PRB_ID}/approvals`]: {
        body: {
          items: [
            {
              id: APPROVAL,
              stage: 1,
              approver_id: TECH,
              origin: 'named',
              route_reason: null,
              state: 'pending',
              decided_at: null,
              decided_by: null,
              channel: null,
              comment: null,
              comment_private: false,
              comments_required: false,
              self_approved: false,
              can_decide: true,
              created_at: '2026-11-05T08:00:00Z',
              version: 1,
            },
          ],
          people: { [TECH]: { display_name: 'Nadia Network', email: 'nadia@example.com' } },
        },
      },
      [`POST /api/v1/problems/${PRB_ID}/approvals/${APPROVAL}/decision`]: { body: {} },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId(`prb-approval-${APPROVAL}-approve`));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));
    await waitFor(() => {
      const sent = fake.calls.find((c) => c.path.endsWith('/decision'));
      expect(sent?.headers.get('If-Match')).toBe('"1"');
      expect((sent?.body as { decision: string }).decision).toBe('approve');
    });
  });

  it('tasks and worklogs use the parts routes of the problem (WP-044c)', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    const fake = api({
      [`GET /api/v1/problems/${PRB_ID}/tasks`]: { body: { items: [], done: 0, total: 0 } },
      [`GET /api/v1/problems/${PRB_ID}/worklogs`]: {
        body: { items: [], total_minutes: 0, people: {} },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('prb-tab-tasks'));
    await waitFor(() => {
      expect(fake.calls.some((c) => c.path === `/api/v1/problems/${PRB_ID}/tasks`)).toBe(true);
    });
    fireEvent.click(screen.getByTestId('prb-tab-worklogs'));
    await waitFor(() => {
      expect(fake.calls.some((c) => c.path === `/api/v1/problems/${PRB_ID}/worklogs`)).toBe(true);
    });
    const incidentParts = (c: { path: string }) =>
      /^\/api\/v1\/incidents\/[^/]+\/(tasks|worklogs)/.test(c.path);
    expect(fake.calls.some(incidentParts)).toBe(false);
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

  it('QA10V-12: the new-problem form is template B: section cards, Cancel then Create', async () => {
    window.history.pushState({}, '', '/problems/new');
    api();
    render(<App />);
    const problem = await screen.findByTestId('prb-section-problem');
    expect(within(problem).getByTestId('prb-subject')).toBeDefined();
    const classification = screen.getByTestId('prb-section-classification');
    // Two fields a row from md up (QA6-PRB-01 kept), each blank select saying what to do.
    expect(
      within(classification).getByTestId('prb-group').closest('.ant-col-md-12'),
    ).not.toBeNull();
    for (const id of ['prb-impact', 'prb-urgency', 'prb-type']) {
      expect(within(classification).getByTestId(id).textContent).toContain('Choose…');
    }
    // The footer: Cancel first, then the primary, outside the cards.
    const cancel = screen.getByTestId('prb-cancel');
    const create = screen.getByTestId('prb-create');
    expect(cancel.compareDocumentPosition(create) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(problem.contains(create)).toBe(false);
  });

  it('QA6-PRB-02: a problem has the breadcrumb Problems / PRB-n and says so in the tab', async () => {
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    api();
    render(<App />);
    await screen.findByTestId('prb-record');
    await waitFor(() => {
      expect(document.title.startsWith('PRB-7 · Problems')).toBe(true);
    });
  });
});
