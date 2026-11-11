import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// The change screens (WP-045d D19, taken forward): the list on template C, the new change on
// template B, the record on template A with its stage rail and moves, the risk questionnaire,
// and a person's risk override that always says why. Every write carries its If-Match.

const CHG_ID = '01a1a2b3-0000-7000-8000-0000000c0001';
const TEMPLATE_ID = '01a1a2b3-0000-7000-8000-0000000c0101';

const change = {
  ...fakeIncident({
    id: CHG_ID,
    display_id: 'CHG-7',
    subject: 'Core switch firmware 9.3',
    status: 'planning_planning',
  }),
  type: 'change',
  stage: 'planning',
  stage_path: 'emergency',
  version: 4,
};

const panel = {
  stage: 'planning',
  stage_path: 'emergency',
  status: 'planning_planning',
  version: 4,
  rail: [
    {
      stage: 'submission',
      state: 'done',
      optional: false,
      entries: [{ entered_at: '2026-11-11T08:00:00Z', left_at: '2026-11-11T09:00:00Z' }],
    },
    {
      stage: 'planning',
      state: 'current',
      optional: false,
      entries: [{ entered_at: '2026-11-11T09:00:00Z', left_at: null }],
    },
    { stage: 'cab_review', state: 'future', optional: false, entries: [] },
  ],
  moves: [
    {
      // Appendix A: the backout plan before the plan goes for approval (REQ-CHG-093).
      to_status: 'planning_awaiting_approval',
      to_stage: 'planning',
      reason_mode: 'none',
      reason_list: null,
      required_fields: ['plan.backout'],
      allowed: true,
      reason: null,
      missing: [{ field: 'plan.backout', code: 'required' }],
    },
    {
      to_status: 'closure_canceled',
      to_stage: 'closure',
      reason_mode: 'required',
      reason_list: null,
      required_fields: [],
      allowed: true,
      reason: null,
      missing: [],
    },
  ],
};

const details = {
  work_item_id: CHG_ID,
  version: 3,
  change_type: 'normal',
  change_reason: null,
  retrospective: false,
  risk: null,
  risk_score: null,
  risk_answers: null,
  risk_version: null,
  risk_chosen: null,
  risk_reason: null,
};

const questionnaire = {
  version: 1,
  questions: [
    {
      code: 'affected',
      answers: [
        { code: 'one_team', score: 0 },
        { code: 'organisation', score: 4 },
      ],
    },
    {
      code: 'critical',
      answers: [
        { code: 'no', score: 0 },
        { code: 'yes', score: 3 },
      ],
    },
  ],
  bands: [
    { low: 0, level: 'low' },
    { low: 4, level: 'medium' },
    { low: 8, level: 'high' },
    { low: 12, level: 'very_high' },
  ],
};

const template = {
  id: TEMPLATE_ID,
  code: 'normal',
  labels: null,
  description: null,
  group_name: null,
  is_default: true,
  for_requesters: false,
  limited_group_ids: [],
  disabled: false,
  copied_from_id: null,
  fields: {},
  custom_fields: {},
  defaults: {},
  lifecycle: 'change',
  stage_path: 'default',
  stage_rules: null,
  version: 1,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

type Routes = NonNullable<Parameters<typeof consoleApi>[0]>['routes'];

function api(extra: Routes = {}) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['tenant_admin'] },
      {
        permissions: ['changes.view', 'changes.create', 'changes.edit'].map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      'GET /api/v1/changes': {
        body: {
          items: [change],
          next_cursor: null,
          has_more: false,
          people: {},
          changes: { [CHG_ID]: { change_type: 'normal', risk: 'high' } },
        },
      },
      [`GET /api/v1/changes/${CHG_ID}`]: { body: change, headers: { ETag: '"4"' } },
      [`GET /api/v1/changes/${CHG_ID}/stages`]: { body: panel },
      [`GET /api/v1/changes/${CHG_ID}/details`]: { body: details },
      [`GET /api/v1/changes/${CHG_ID}/risk/questionnaire`]: { body: questionnaire },
      [`GET /api/v1/changes/${CHG_ID}/approvals`]: { body: { items: [], people: {} } },
      [`GET /api/v1/changes/${CHG_ID}/plan`]: {
        body: [{ section: 'backout', content: null, version: 0 }],
      },
      'GET /api/v1/changes/templates': { body: [template] },
      'GET /api/v1/changes/list-settings/open': {
        body: { view_key: 'open', columns: [], sort: null, page_size: 50, version: null },
      },
      'GET /api/v1/changes/settings': {
        body: {
          statuses: [
            {
              code: 'planning_planning',
              category: 'open',
              colour: '#1677ff',
              labels: null,
              system: false,
              disabled: false,
              resume_on_requester_reply: false,
            },
          ],
          closure_codes: [],
          own_lists: {
            change_type: [{ code: 'normal', labels: null, disabled: false }],
            change_reason: [{ code: 'security_fix', labels: null, disabled: false }],
          },
        },
      },
      'POST /api/v1/changes': { status: 201, body: change },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

async function choose(testId: string, title: string) {
  const select = (await screen.findByTestId(testId)).querySelector('.ant-select-selector');
  if (select === null) throw new Error('not an Ant Design Select');
  fireEvent.mouseDown(select);
  fireEvent.click(await screen.findByTitle(title));
}

describe('console: changes', () => {
  it('template C: lists changes with path, type, risk, stage, status and the emergency flag; Pending approval is a view', async () => {
    window.history.pushState({}, '', '/changes');
    const fake = api();
    render(<App />);
    const row = await screen.findByTestId('change-row-CHG-7');
    expect(within(row).getByText('Core switch firmware 9.3')).toBeTruthy();
    expect(within(row).getByTestId('change-stage-CHG-7').textContent).toBe('Planning');
    expect(within(row).getByText('Emergency path')).toBeTruthy();
    expect(within(row).getByTestId('change-link-CHG-7').tagName).toBe('A');
    expect(screen.getByTestId('change-emergency-CHG-7').textContent).toContain('Emergency');
    // REQ-CHG-098: each row carries its type and the risk in force.
    expect(within(row).getByText('Normal')).toBeTruthy();
    expect(within(row).getByTestId('change-risk-CHG-7').textContent).toBe('High');
    expect(screen.getByTestId('new-change')).toBeTruthy();
    expect(fake.find('GET', '/api/v1/changes')[0]?.url.searchParams.get('view')).toBe('open');
    await choose('changes-view', 'Pending approval');
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/changes').at(-1);
      expect(last?.url.searchParams.get('view')).toBe('pending_approval');
    });
  });

  it('REQ-CHG-101: picked changes close together; assign, take and close only, and skips say why', async () => {
    const JOB_ID = '01a1a2b3-0000-7000-8000-0000000c0d01';
    window.history.pushState({}, '', '/changes');
    const fake = api({
      'GET /api/v1/changes/settings': {
        body: {
          statuses: [],
          closure_codes: [{ code: 'fixed', labels: null, disabled: false }],
          own_lists: {},
        },
      },
      'POST /api/v1/changes/bulk': {
        status: 202,
        body: {
          id: JOB_ID,
          action: 'close',
          status: 'queued',
          total: 1,
          processed: 0,
          done_count: 0,
          skipped_count: 0,
          results: [],
          created_at: '2027-03-01T00:00:00Z',
          started_at: null,
          finished_at: null,
        },
      },
      [`GET /api/v1/changes/bulk-jobs/${JOB_ID}`]: {
        body: {
          id: JOB_ID,
          action: 'close',
          status: 'done',
          total: 1,
          processed: 1,
          done_count: 0,
          skipped_count: 1,
          results: [
            {
              id: CHG_ID,
              display_id: 'CHG-7',
              outcome: 'skipped',
              code: 'stage_move_refused',
              params: { reason: 'children_open', reasons: 'children_open' },
            },
          ],
          created_at: '2027-03-01T00:00:00Z',
          started_at: '2027-03-01T00:00:01Z',
          finished_at: '2027-03-01T00:00:02Z',
        },
      },
    });
    render(<App />);
    const row = await screen.findByTestId('change-row-CHG-7');
    fireEvent.click(within(row).getByRole('checkbox'));
    expect((await screen.findByTestId('inc-selected')).textContent).toBe('1 change selected');
    for (const action of ['close', 'assign', 'take']) {
      expect(screen.getByTestId(`inc-bulk-${action}`)).toBeTruthy();
    }
    for (const action of ['cancel', 'delete', 'edit', 'resolve']) {
      expect(screen.queryByTestId(`inc-bulk-${action}`)).toBeNull();
    }
    fireEvent.click(screen.getByTestId('inc-bulk-close'));
    await choose('chg-bulk-closure-code', 'Fixed');
    fireEvent.change(screen.getByTestId('chg-bulk-closing-text'), {
      target: { value: 'Done in the window.' },
    });
    fireEvent.click(screen.getByTestId('chg-bulk-close-ok'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/changes/bulk')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/changes/bulk')[0]?.body).toEqual({
      action: 'close',
      changes: { closure_code: 'fixed', resolution: 'Done in the window.' },
      record_ids: [CHG_ID],
      all_matching: false,
    });
    const drawer = await screen.findByTestId('inc-bulk-progress');
    const skipped = await within(drawer).findByTestId('inc-bulk-skipped-CHG-7');
    expect(skipped.textContent).toContain('Close or cancel its child changes and releases first.');
    expect(within(skipped).getByRole('link').getAttribute('href')).toBe(`/changes/${CHG_ID}`);
    expect(within(drawer).getByText('1 change was skipped')).toBeTruthy();
  });

  it('REQ-CHG-101: take runs on the change list’s own bulk route, in change words', async () => {
    window.history.pushState({}, '', '/changes');
    const fake = api({
      'POST /api/v1/changes/bulk': {
        status: 202,
        body: {
          id: 'job-take',
          action: 'take',
          status: 'queued',
          total: 1,
          processed: 0,
          done_count: 0,
          skipped_count: 0,
          results: [],
          created_at: '2027-03-01T00:00:00Z',
          started_at: null,
          finished_at: null,
        },
      },
    });
    render(<App />);
    const row = await screen.findByTestId('change-row-CHG-7');
    fireEvent.click(within(row).getByRole('checkbox'));
    fireEvent.click(await screen.findByTestId('inc-bulk-take'));
    const dialog = await screen.findByTestId('inc-bulk-dialog');
    expect(dialog.textContent).toContain(
      'You become the change owner of each change you can take.',
    );
    expect(dialog.textContent).toContain('Take 1 change');
    fireEvent.click(screen.getByTestId('inc-bulk-start'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/changes/bulk')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/changes/bulk')[0]?.body).toMatchObject({
      action: 'take',
      record_ids: [CHG_ID],
    });
    // Never the incident settings or routes from the change list.
    expect(fake.calls.filter((c) => c.path.startsWith('/api/v1/incidents/'))).toEqual([]);
  });

  it('template B: a new change from the default template, once, then its risk questionnaire', async () => {
    window.history.pushState({}, '', '/changes/new');
    const fake = api();
    render(<App />);
    expect(await screen.findByTestId('change-path')).toBeTruthy();
    const save = screen.getByTestId('change-save');
    expect(save).toHaveProperty('disabled', true); // no title yet
    fireEvent.change(screen.getByTestId('change-subject'), {
      target: { value: 'Core switch firmware 9.3' },
    });
    await choose('change-reason', 'Security fix');
    fireEvent.click(screen.getByTestId('change-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/changes')).toHaveLength(1);
    });
    const [made] = fake.find('POST', '/api/v1/changes');
    expect(made?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(made?.body).toMatchObject({
      subject: 'Core switch firmware 9.3',
      template_id: TEMPLATE_ID,
      change_reason: 'security_fix',
    });
    // It opens on the Risk tab: the questionnaire is the template's, so the change comes first.
    expect(await screen.findByTestId('change-risk')).toBeTruthy();
    expect(window.location.search).toBe('?tab=risk');
  });

  it('an unknown ?template= falls back to the default template, quietly (lane A, #404)', async () => {
    window.history.pushState({}, '', '/changes/new?template=01a1a2b3-0000-7000-8000-0000000dead0');
    const fake = api();
    render(<App />);
    // The default's path shows and the form can be sent, as with no template asked for.
    expect(await screen.findByTestId('change-path')).toBeTruthy();
    fireEvent.change(screen.getByTestId('change-subject'), { target: { value: 'Patch' } });
    expect(screen.getByTestId('change-save')).toHaveProperty('disabled', false);
    fireEvent.click(screen.getByTestId('change-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/changes')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/changes')[0]?.body).toMatchObject({
      template_id: TEMPLATE_ID,
    });
  });

  it('template A: the rail, one primary move, and a plan the move needs is named, not typed', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}`);
    api();
    render(<App />);
    expect(await screen.findByTestId('change-stages')).toBeTruthy();
    expect(screen.getByTestId('change-emergency')).toBeTruthy();
    expect(screen.getByTestId('change-props').textContent).toContain('Normal');
    // Canceling is never beside the positive move: it is under More.
    const moves = screen.getByTestId('change-moves');
    expect(within(moves).queryByTestId('move-closure_canceled')).toBeNull();
    fireEvent.click(within(moves).getByTestId('move-planning_awaiting_approval'));
    const dialog = await screen.findByTestId('move-dialog');
    expect(within(dialog).getByTestId('move-plan-backout').textContent).toContain('Backout plan');
    expect(screen.getByTestId('move-ok')).toHaveProperty('disabled', true);
  });

  it('REQ-CHG-057: the questionnaire scores as you answer; the assessment carries the details version', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}?tab=risk`);
    const fake = api({
      [`PUT /api/v1/changes/${CHG_ID}/risk/assessment`]: {
        body: { ...details, version: 4, risk: 'medium', risk_score: 4 },
      },
    });
    render(<App />);
    const risk = await screen.findByTestId('change-risk');
    expect(screen.getByTestId('change-risk-save')).toHaveProperty('disabled', true);
    fireEvent.click(within(risk).getByLabelText('The whole organisation'));
    fireEvent.click(within(risk).getByLabelText('No'));
    expect(risk.textContent).toContain('Score: 4');
    expect(screen.getByTestId('change-risk-level').textContent).toContain('Medium');
    fireEvent.click(screen.getByTestId('change-risk-save'));
    await waitFor(() => {
      expect(fake.find('PUT', `/api/v1/changes/${CHG_ID}/risk/assessment`)).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', `/api/v1/changes/${CHG_ID}/risk/assessment`);
    expect(sent?.headers.get('If-Match')).toBe('"3"');
    expect(sent?.body).toEqual({ answers: { affected: 'organisation', critical: 'no' } });
  });

  it('REQ-CHG-060: setting the risk by hand asks why before it saves', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}`);
    const fake = api({
      [`PATCH /api/v1/changes/${CHG_ID}/details`]: {
        body: { ...details, version: 4, risk: 'high', risk_chosen: 'high' },
      },
      // Nothing approved yet: the new risk sends no stage back.
      [`POST /api/v1/changes/${CHG_ID}/approvals/reapproval-preview`]: { body: [] },
    });
    render(<App />);
    await screen.findByTestId('change-details');
    await choose('change-risk-chosen', 'High');
    const save = await screen.findByTestId('change-details-save');
    expect(save).toHaveProperty('disabled', true);
    fireEvent.change(screen.getByTestId('change-risk-reason'), {
      target: { value: 'Touches the payment core' },
    });
    fireEvent.click(screen.getByTestId('change-details-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/changes/${CHG_ID}/details`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/changes/${CHG_ID}/details`);
    expect(sent?.headers.get('If-Match')).toBe('"3"');
    expect(sent?.body).toEqual({ risk_chosen: 'high', risk_reason: 'Touches the payment core' });
  });

  it('REQ-CHG-053: a new risk that sends an approved stage back says so before saving', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}`);
    const fake = api({
      [`POST /api/v1/changes/${CHG_ID}/approvals/reapproval-preview`]: {
        body: [
          {
            stage: 'cab_review',
            changes: [{ field: 'risk', before: 'low', after: 'high', effect: 'restart' }],
          },
        ],
      },
      [`PATCH /api/v1/changes/${CHG_ID}/details`]: {
        body: { ...details, version: 4, risk: 'high', risk_chosen: 'high' },
      },
    });
    render(<App />);
    await screen.findByTestId('change-details');
    await choose('change-risk-chosen', 'High');
    fireEvent.change(await screen.findByTestId('change-risk-reason'), {
      target: { value: 'Touches the payment core' },
    });
    fireEvent.click(screen.getByTestId('change-details-save'));
    const warning = await screen.findByTestId('reapproval-warning');
    expect(warning.textContent).toContain('CAB review');
    expect(fake.find('PATCH', `/api/v1/changes/${CHG_ID}/details`)).toHaveLength(0);
    expect(
      fake.find('POST', `/api/v1/changes/${CHG_ID}/approvals/reapproval-preview`)[0]?.body,
    ).toEqual({ risk: 'high' });
    fireEvent.click(screen.getByTestId('reapproval-ok'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/changes/${CHG_ID}/details`)).toHaveLength(1);
    });
  });

  it('QA-2026-11-11 F-02: the roles tab names the change\'s own requester, not "Nobody yet"', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}?tab=roles`);
    const SANA = '01a1a2b3-0000-7000-8000-00000000aa01';
    api({
      [`GET /api/v1/changes/${CHG_ID}/roles`]: {
        body: {
          version: 4,
          roles: [
            {
              code: 'requester',
              labels: null,
              single: true,
              system: true,
              disabled: false,
              user_ids: [SANA],
              group_ids: [],
              from_record: true,
            },
          ],
          people: { [SANA]: 'Sana Malik' },
        },
      },
    });
    render(<App />);
    const holder = await screen.findByTestId('change-role-requester-holder');
    expect(holder.textContent).toContain('Sana Malik');
    expect(holder.textContent).toContain('Set in the details panel');
    expect(screen.getByTestId('change-roles').textContent).not.toContain('Nobody yet');
  });

  it('QA-2026-11-11 F-03: history shows labels and local times, never codes, UTC or bookkeeping', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}?tab=history`);
    api({
      [`GET /api/v1/changes/${CHG_ID}/history`]: {
        body: {
          items: [
            {
              change_id: 'h-1',
              version: 2,
              kind: 'updated',
              occurred_at: '2026-11-11T14:18:00Z',
              actor_type: 'user',
              actor_id: null,
              actor_name: 'Sana Malik',
              source: 'ui',
              reason: null,
              automation: null,
              changes: [
                { field: 'risk', old: null, new: 'very_high' },
                { field: 'risk_answers', old: null, new: { affected: 'organisation' } },
                { field: 'risk_version', old: null, new: 1 },
                { field: 'scheduled_start', old: null, new: '2026-11-17T21:00:00+00:00' },
                { field: 'change_reason', old: null, new: 'security_fix' },
                { field: 'stage', old: 'planning', new: 'submission' },
                { field: 'reapproval_restarted', old: null, new: ['risk'] },
                { field: 'task.extra_cost', old: null, new: null, hidden: true },
              ],
            },
          ],
          next_cursor: null,
          people: {},
        },
      },
    });
    render(<App />);
    const entry = await screen.findByTestId('inc-history-entry');
    const text = entry.textContent;
    expect(text).toContain('Very high');
    expect(text).not.toContain('very_high');
    expect(text).toContain('Risk assessment answers');
    expect(text).not.toMatch(/Risk Version|risk_version/);
    expect(text).not.toContain('2026-11-17T21:00');
    expect(text).not.toContain('+00:00');
    expect(text).not.toContain('security_fix');
    // The re-check (2d848b42): a stage by its name, and a send-back as one sentence.
    expect(text).toContain('from Planning to Submission');
    expect(text).not.toMatch(/planning to submission|because of to/);
    expect(text).toContain('Sana Malik sent it back for approval again because Risk changed');
    // A task's extra cost not the reader's to see (lane B's #398 review): only that it changed.
    expect(text).toContain('Sana Malik changed Extra cost');
  });

  it('QA-2026-11-11 F-01: a form that remounts keeps its Idempotency-Key, so a repeat never duplicates', async () => {
    window.history.pushState({}, '', '/changes/new');
    const fake = api({
      'POST /api/v1/changes': {
        status: 503,
        body: {
          type: 'urn:supportx:problem:service_unavailable',
          title: 'Service Unavailable',
          status: 503,
          code: 'service_unavailable',
          message_key: 'errors.service_unavailable',
          params: {},
          errors: [],
        },
      },
    });
    const fill = async () => {
      expect(await screen.findByTestId('change-path')).toBeTruthy();
      fireEvent.change(screen.getByTestId('change-subject'), {
        target: { value: 'Core switch firmware 9.3' },
      });
      fireEvent.click(screen.getByTestId('change-save'));
    };
    const first = render(<App />);
    await fill();
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/changes')).toHaveLength(1);
    });
    first.unmount(); // the page remounts (a banner, a session refetch)
    render(<App />);
    await fill();
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/changes')).toHaveLength(2);
    });
    const [one, two] = fake.find('POST', '/api/v1/changes');
    expect(one?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(two?.headers.get('Idempotency-Key')).toBe(one?.headers.get('Idempotency-Key'));
  });
});
