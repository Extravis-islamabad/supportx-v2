import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// The change screens, PR 2: the CAB and approvals panel, the approver preview before a stage is
// raised, the emergency override (D-144), and the change advisory boards on template E.

const CHG_ID = '01a1a2b3-0000-7000-8000-0000000c0002';
const BOARD_ID = '01a1a2b3-0000-7000-8000-0000000cb001';
const MEMBER = '01a1a2b3-0000-7000-8000-0000000c0a01';
const LEFT_OUT = '01a1a2b3-0000-7000-8000-0000000c0a02';
const APPROVAL_ID = '01a1a2b3-0000-7000-8000-0000000c0e01';

const change = {
  ...fakeIncident({
    id: CHG_ID,
    display_id: 'CHG-9',
    subject: 'Firewall rule base clean-up',
    status: 'cab_awaiting',
  }),
  type: 'change',
  stage: 'cab_review',
  stage_path: 'default',
  version: 6,
};

const details = {
  work_item_id: CHG_ID,
  version: 6,
  change_type: 'normal',
  change_reason: null,
  retrospective: false,
  risk: 'high',
  risk_score: 9,
  risk_answers: null,
  risk_version: 1,
  risk_chosen: null,
  risk_reason: null,
  sent_back: false,
};

const approval = {
  id: APPROVAL_ID,
  stage: 1,
  record_stage: 'cab_review',
  rule: 'majority',
  approver_id: MEMBER,
  origin: 'named',
  route_reason: null,
  board_id: BOARD_ID,
  board_reason: 'mapped',
  advisory: false,
  state: 'pending',
  decided_at: null,
  decided_by: null,
  channel: null,
  comment: null,
  comment_private: false,
  comments_required: false,
  self_approved: false,
  can_decide: true,
  created_at: '2026-11-11T10:00:00Z',
  version: 2,
};

const board = {
  id: BOARD_ID,
  code: null,
  name: 'Network CAB',
  labels: { en: 'Network CAB' },
  description: null,
  chair_id: null,
  rule: 'majority',
  mapping: { change_types: ['normal'], risk_levels: ['high'], site_ids: [], template_ids: [] },
  position: 1,
  is_default: false,
  members: [{ user_id: MEMBER, group_id: null, optional: false }],
  version: 3,
  people: { [MEMBER]: { display_name: 'Sara Khan', email: 'sara@example.com' } },
};
const seeded = {
  ...board,
  id: '01a1a2b3-0000-7000-8000-0000000cb000',
  code: 'cab',
  name: 'Change advisory board',
  labels: null,
  mapping: null,
  position: 9,
  is_default: true,
  members: [],
  people: {},
};

const panel = (moves: object[]) => ({
  stage: 'cab_review',
  stage_path: 'default',
  status: 'cab_awaiting',
  version: 6,
  rail: [{ stage: 'cab_review', state: 'current', optional: false, entries: [] }],
  moves,
});

const PERMISSIONS = [
  'changes.view',
  'changes.edit',
  'changes.emergency_override',
  'changes.manage_boards',
];

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

type Routes = NonNullable<Parameters<typeof consoleApi>[0]>['routes'];

function api(extra: Routes = {}, permissions = PERMISSIONS) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['technician'] },
      {
        permissions: permissions.map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      [`GET /api/v1/changes/${CHG_ID}`]: { body: change, headers: { ETag: '"6"' } },
      [`GET /api/v1/changes/${CHG_ID}/stages`]: { body: panel([]) },
      [`GET /api/v1/changes/${CHG_ID}/details`]: { body: details },
      [`GET /api/v1/changes/${CHG_ID}/approvals`]: {
        body: {
          items: [approval],
          people: { [MEMBER]: { display_name: 'Sara Khan', email: 'sara@example.com' } },
        },
      },
      [`GET /api/v1/changes/${CHG_ID}/approvals/changes-since`]: { body: [] },
      'GET /api/v1/change-boards': { body: [board, seeded] },
      'GET /api/v1/changes/settings': {
        body: {
          statuses: [],
          closure_codes: [],
          own_lists: { change_type: [{ code: 'normal', labels: null, disabled: false }] },
        },
      },
      'GET /api/v1/changes/templates': { body: [] },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: change approvals', () => {
  it('REQ-CHG-042: each approval names its board and why, and a decision carries its If-Match', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}?tab=approvals`);
    const fake = api({
      [`POST /api/v1/changes/${CHG_ID}/approvals/${APPROVAL_ID}/decision`]: {
        body: { ...approval, state: 'approved', version: 3 },
      },
      [`GET /api/v1/changes/${CHG_ID}/approvals/changes-since`]: {
        body: [
          {
            stage: 'planning',
            changes: [{ field: 'risk', before: 'medium', after: 'high', effect: 'notify' }],
          },
        ],
      },
    });
    render(<App />);
    const row = await screen.findByTestId(`approval-${APPROVAL_ID}`);
    expect(within(row).getByTestId(`approval-${APPROVAL_ID}-board`).textContent).toBe(
      'Network CAB (its rules matched this change)',
    );
    expect(row.textContent).toContain('Sara Khan');
    expect(row.textContent).toContain('A majority');
    expect(screen.getByTestId('change-changes-since').textContent).toContain('Planning');
    fireEvent.click(within(row).getByTestId(`approval-${APPROVAL_ID}-approve`));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));
    await waitFor(() => {
      expect(
        fake.find('POST', `/api/v1/changes/${CHG_ID}/approvals/${APPROVAL_ID}/decision`),
      ).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/changes/${CHG_ID}/approvals/${APPROVAL_ID}/decision`);
    expect(sent?.headers.get('If-Match')).toBe('"2"');
    expect(sent?.body).toMatchObject({ decision: 'approve' });
  });

  it('REQ-CHG-039: the move that raises the CAB says who would approve and who is left out', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}`);
    api({
      [`GET /api/v1/changes/${CHG_ID}/stages`]: {
        body: panel([
          {
            to_status: 'cab_awaiting',
            to_stage: 'cab_review',
            reason_mode: 'none',
            reason_list: null,
            required_fields: [],
            allowed: true,
            reason: null,
            missing: [],
          },
        ]),
      },
      [`GET /api/v1/changes/${CHG_ID}/approvals/preview`]: {
        body: {
          stage: 'cab_review',
          approver_ids: [MEMBER],
          barred: [{ user_id: LEFT_OUT, reason: 'segregation_of_duties' }],
          fallback_reason: null,
          people: {
            [MEMBER]: { display_name: 'Sara Khan', email: 'sara@example.com' },
            [LEFT_OUT]: { display_name: 'Ali Raza', email: 'ali@example.com' },
          },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('move-cab_awaiting'));
    const preview = await screen.findByTestId('approval-preview');
    expect(preview.textContent).toContain('Approval goes to Sara Khan.');
    expect(within(preview).getByTestId(`preview-barred-${LEFT_OUT}`).textContent).toContain(
      'Ali Raza',
    );
  });

  it('D-144: the emergency override shows only on a change sent back, and needs a reason', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}`);
    const fake = api({
      [`GET /api/v1/changes/${CHG_ID}/details`]: { body: { ...details, sent_back: true } },
      [`POST /api/v1/changes/${CHG_ID}/emergency-override`]: {
        body: { ...change, status: 'implementation_scheduled', version: 7 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('change-more'));
    fireEvent.click(await screen.findByTestId('change-emergency-override'));
    const ok = await screen.findByTestId('override-ok');
    expect(ok).toHaveProperty('disabled', true);
    fireEvent.change(screen.getByTestId('override-reason'), {
      target: { value: 'Half the firewalls are already done' },
    });
    fireEvent.click(screen.getByTestId('override-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/changes/${CHG_ID}/emergency-override`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/changes/${CHG_ID}/emergency-override`);
    expect(sent?.headers.get('If-Match')).toBe('"6"');
    expect(sent?.body).toEqual({ reason: 'Half the firewalls are already done' });
  });

  it('D-144: without the permission there is no override, even on a change sent back', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}`);
    api({ [`GET /api/v1/changes/${CHG_ID}/details`]: { body: { ...details, sent_back: true } } }, [
      'changes.view',
      'changes.edit',
    ]);
    render(<App />);
    await screen.findByTestId('change-stages');
    expect(screen.queryByTestId('change-more')).toBeNull();
  });
});

describe('console: change advisory boards', () => {
  it('template E: boards in order; the default one cannot be deleted; an edit carries If-Match', async () => {
    window.history.pushState({}, '', '/admin/change-boards');
    const fake = api({
      [`PATCH /api/v1/change-boards/${BOARD_ID}`]: { body: { ...board, version: 4 } },
    });
    render(<App />);
    const table = await screen.findByTestId('boards-table');
    await waitFor(() => {
      expect(table.textContent).toContain('Network CAB');
    });
    expect(table.textContent).toContain('Change advisory board');
    expect(screen.getByTestId(`board-${seeded.id}-no-members`)).toBeTruthy();
    expect(screen.getByTestId(`board-${seeded.id}-remove`)).toHaveProperty('disabled', true);
    fireEvent.click(screen.getByTestId(`board-${BOARD_ID}-edit`));
    const members = await screen.findByTestId('board-members');
    expect(members.textContent).toContain('Sara Khan');
    // The chair rule needs a chair: the save says why it waits.
    const rule = (await screen.findByTestId('board-rule')).querySelector('.ant-select-selector');
    if (rule === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(rule);
    fireEvent.click(await screen.findByTitle('A majority; the chair breaks ties'));
    const chair = screen.getByTestId('board-chair').querySelector('.ant-select-selector');
    if (chair === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(chair);
    fireEvent.click(await screen.findByTitle('Sara Khan'));
    fireEvent.click(
      within(screen.getByTestId('board-editor')).getByRole('button', { name: 'Save' }),
    );
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/change-boards/${BOARD_ID}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/change-boards/${BOARD_ID}`);
    expect(sent?.headers.get('If-Match')).toBe('"3"');
    expect(sent?.body).toMatchObject({
      rule: 'majority_with_chair',
      chair_id: MEMBER,
      members: [{ user_id: MEMBER, optional: false }],
    });
  });
});
