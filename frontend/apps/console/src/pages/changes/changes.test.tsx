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
        body: { items: [change], next_cursor: null, has_more: false, people: {} },
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
  it('template C: lists changes with path, stage, status and the emergency flag; Pending approval is a view', async () => {
    window.history.pushState({}, '', '/changes');
    const fake = api();
    render(<App />);
    const row = await screen.findByTestId('change-row-CHG-7');
    expect(within(row).getByText('Core switch firmware 9.3')).toBeTruthy();
    expect(within(row).getByTestId('change-stage-CHG-7').textContent).toBe('Planning');
    expect(within(row).getByText('Emergency path')).toBeTruthy();
    expect(within(row).getByTestId('change-link-CHG-7').tagName).toBe('A');
    expect(screen.getByTestId('change-emergency-CHG-7').textContent).toContain('Emergency');
    expect(screen.getByTestId('new-change')).toBeTruthy();
    expect(fake.find('GET', '/api/v1/changes')[0]?.url.searchParams.get('view')).toBe('open');
    await choose('changes-view', 'Pending approval');
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/changes').at(-1);
      expect(last?.url.searchParams.get('view')).toBe('pending_approval');
    });
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
});
