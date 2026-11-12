import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeCustomField,
  fakeIncident,
  fakeSession,
  fakeUser,
  problem,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-058a s6: releases in the console: the list (stage, status, the emergency flag), the stage
// rail with its moves, a move's dialog asking only for what the move needs, and If-Match on it.

const REL_ID = '01a1a2b3-0000-7000-8000-0000000e0001';

const release = {
  ...fakeIncident({
    id: REL_ID,
    display_id: 'REL-1',
    subject: 'Payroll 4.2',
    status: 'build_in_progress',
  }),
  type: 'release',
  stage: 'build',
  stage_path: 'emergency',
  version: 7,
};

const panel = {
  stage: 'build',
  stage_path: 'emergency',
  status: 'build_in_progress',
  version: 7,
  rail: [
    {
      stage: 'submission',
      state: 'done',
      optional: false,
      entries: [{ entered_at: '2026-11-05T08:00:00Z', left_at: '2026-11-05T09:00:00Z' }],
    },
    {
      stage: 'build',
      state: 'current',
      optional: false,
      entries: [{ entered_at: '2026-11-05T09:00:00Z', left_at: null }],
    },
    { stage: 'testing', state: 'future', optional: false, entries: [] },
  ],
  moves: [
    {
      to_status: 'build_completed',
      to_stage: 'build',
      reason_mode: 'none',
      reason_list: null,
      required_fields: [],
      allowed: true,
      reason: null,
      missing: [{ field: 'release_version', code: 'required_to_leave_stage' }],
    },
    {
      to_status: 'build_backed_out',
      to_stage: 'build',
      reason_mode: 'required',
      reason_list: null,
      required_fields: [],
      allowed: true,
      reason: null,
      missing: [],
    },
    {
      to_status: 'testing_in_progress',
      to_stage: 'testing',
      reason_mode: 'none',
      reason_list: null,
      required_fields: [],
      allowed: true,
      reason: null,
      missing: [
        { field: 'release_type', code: 'required_to_leave_stage' },
        { field: 'release_manager_id', code: 'required_to_leave_stage' },
        { field: 'custom.cab_ref', code: 'required_to_leave_stage' },
      ],
    },
    {
      to_status: 'closure_canceled',
      to_stage: 'closure',
      reason_mode: 'required',
      reason_list: null,
      required_fields: [],
      allowed: false,
      reason: 'stage_access',
      missing: [],
    },
  ],
};

const APPROVAL_ID = '01a1a2b3-0000-7000-8000-0000000a0001';
const approval = {
  id: APPROVAL_ID,
  stage: 1,
  record_stage: 'planning',
  rule: 'any',
  approver_id: '01a1a2b3-0000-7000-8000-0000000b0001',
  origin: 'named',
  route_reason: null,
  state: 'pending',
  decided_at: null,
  decided_by: null,
  channel: null,
  comment: null,
  comment_private: false,
  comments_required: true,
  self_approved: false,
  can_decide: true,
  created_at: '2026-11-05T08:00:00Z',
  version: 2,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(
  extra: Parameters<typeof consoleApi>[0] extends infer A
    ? A extends { routes?: infer R }
      ? R
      : never
    : never = {},
  permissions: string[] = ['releases.view', 'releases.create', 'releases.edit'],
) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['tenant_admin'] },
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
      'GET /api/v1/releases': {
        body: { items: [release], next_cursor: null, has_more: false, people: {} },
      },
      [`GET /api/v1/releases/${REL_ID}`]: { body: release, headers: { ETag: '"7"' } },
      [`GET /api/v1/releases/${REL_ID}/stages`]: { body: panel },
      [`GET /api/v1/releases/${REL_ID}/details`]: {
        body: {
          work_item_id: REL_ID,
          version: 7,
          release_type: null,
          risk: null,
          release_version: null,
          build_ref: null,
          release_reason: null,
          release_notes: null,
          scheduled_start: null,
          scheduled_end: null,
          actual_start: null,
          actual_end: null,
          release_manager_id: null,
          release_engineer_id: null,
        },
      },
      'GET /api/v1/releases/list-settings/open': {
        body: { view_key: 'open', columns: [], sort: null, page_size: 50, version: null },
      },
      'PUT /api/v1/releases/list-settings/open': (call: { body: unknown }) => ({
        body: { view_key: 'open', version: 1, ...(call.body as object) },
        headers: { ETag: '"1"' },
      }),
      'GET /api/v1/releases/settings': {
        body: {
          // The type's statuses, as the API sends them: the list's status dot (QA10V-06).
          statuses: [
            {
              code: 'build_in_progress',
              category: 'open',
              colour: '#1677ff',
              labels: null,
              system: false,
              disabled: false,
              resume_on_requester_reply: false,
            },
          ],
          closure_codes: [],
          own_lists: { release_type: [{ code: 'major', labels: null, disabled: false }] },
        },
      },
      'GET /api/v1/custom-fields': {
        body: [
          fakeCustomField({ entity: 'release', key: 'cab_ref', labels: { en: 'CAB reference' } }),
        ],
      },
      [`POST /api/v1/releases/${REL_ID}/moves`]: { body: { ...release, version: 8 } },
      [`GET /api/v1/releases/${REL_ID}/approvals`]: { body: { items: [approval] } },
      [`POST /api/v1/releases/${REL_ID}/approvals/${APPROVAL_ID}/decision`]: {
        body: { ...approval, state: 'rejected', version: 3 },
      },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: releases', () => {
  it('lists releases with their stage, status and the emergency flag', async () => {
    window.history.pushState({}, '', '/releases');
    api();
    render(<App />);
    const row = await screen.findByTestId('release-row-REL-1');
    expect(within(row).getByText('Payroll 4.2')).toBeTruthy();
    expect(within(row).getByText('Build')).toBeTruthy();
    expect(within(row).getByText('In progress')).toBeTruthy();
    expect(screen.getByTestId('release-emergency-REL-1').textContent).toContain('Emergency');
    expect(screen.getByTestId('new-release')).toBeTruthy();
  });

  it('template C: the count, quick views and search go to the API, in one filter bar', async () => {
    window.history.pushState({}, '', '/releases');
    const fake = api();
    render(<App />);
    const row = await screen.findByTestId('release-row-REL-1');
    // The ID is a link and the status a dot chip (QA10V-06).
    expect(within(row).getByTestId('release-link-REL-1').tagName).toBe('A');
    expect(within(row).getByTestId('inc-status').querySelector('.ant-badge')).not.toBeNull();
    const bar = screen.getByTestId('releases-filters');
    expect(within(bar).getByTestId('releases-view')).toBeTruthy();
    expect(within(bar).getByTestId('releases-search')).toBeTruthy();
    const first = fake.find('GET', '/api/v1/releases')[0];
    expect(first?.url.searchParams.get('view')).toBe('open');
    expect(first?.url.searchParams.get('include_total')).toBe('true');
    // The view select, as on every list (QA10V-06; it was segmented tabs).
    const selector = within(bar).getByTestId('releases-view').querySelector('.ant-select-selector');
    if (selector === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(selector);
    fireEvent.click(await screen.findByTitle('All'));
    fireEvent.change(within(bar).getByRole('searchbox'), { target: { value: 'rel-1' } });
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/releases').at(-1);
      expect(last?.url.searchParams.get('view')).toBeNull();
      expect(JSON.parse(last?.url.searchParams.get('filter') ?? 'null')).toEqual({
        or: [
          { field: 'subject', op: 'contains', value: 'rel-1' },
          { field: 'display_id', op: 'eq', value: 'REL-1' },
        ],
      });
    });
  });

  it('Haider 2026-11-10: a column resized by keyboard is kept per view; Reset widths clears it', async () => {
    window.history.pushState({}, '', '/releases');
    const fake = api();
    render(<App />);
    await screen.findByTestId('release-row-REL-1');
    expect(screen.queryByTestId('releases-reset-widths')).toBeNull(); // nothing to reset yet
    const [subject] = screen.getAllByRole('separator', { name: /Subject/ });
    if (subject === undefined) throw new Error('no resize handle on the subject');
    expect(subject.getAttribute('aria-valuemin')).toBe('180');
    fireEvent.keyDown(subject, { key: 'ArrowRight' });
    const last = () =>
      fake.find('PUT', '/api/v1/releases/list-settings/open').at(-1)?.body as {
        columns: { key: string; width: number | null }[];
      };
    await waitFor(() => {
      expect(last().columns.find((c) => c.key === 'subject')?.width).toBeGreaterThanOrEqual(180);
    });
    expect(last().columns.map((c) => c.key)).toEqual([
      'id',
      'subject',
      'stage',
      'status',
      'updated',
    ]);
    fireEvent.click(await screen.findByTestId('releases-reset-widths'));
    await waitFor(() => {
      expect(last().columns.every((c) => c.width === null)).toBe(true);
    });
  });

  it('template B: a new release is one section card with Cancel before Create in the footer', async () => {
    window.history.pushState({}, '', '/releases/new');
    const routed = consoleApi({
      me: fakeSession(),
      routes: {
        'GET /api/v1/releases/templates': {
          body: [
            {
              id: 'tpl-1',
              code: 'standard',
              labels: { en: 'Standard release' },
              is_default: true,
              disabled: false,
              stage_path: null,
            },
          ],
        },
      },
    });
    restore = routed.restore;
    render(<App />);
    const footer = await screen.findByTestId('new-release-footer');
    const buttons = [...footer.querySelectorAll('button')].map((b) =>
      b.getAttribute('data-testid'),
    );
    expect(buttons).toEqual(['release-cancel', 'release-save']);
    // QA10-P4-16: a template with no path of its own still names the path it takes.
    expect((await screen.findByTestId('release-path')).textContent).toBe(
      'This template takes the Standard path.',
    );
    expect(
      screen.getByTestId('release-section').querySelector('button[data-testid="release-save"]'),
    ).toBeNull();
  });

  it('shows the rail, says why a move is not possible, and asks for the reason a move needs', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const fake = api();
    render(<App />);
    expect(await screen.findByTestId('release-rail')).toBeTruthy();
    expect(screen.getByTestId('rail-build').textContent).toContain('Build');
    // QA6-REL-01: a move not possible now is in More, out of the way, saying why (REQ-WI-010).
    expect(screen.queryByTestId('move-closure_canceled')).toBeNull();
    fireEvent.click(screen.getByTestId('release-more'));
    const canceled = await screen.findByTestId('move-closure_canceled');
    expect(canceled.getAttribute('aria-disabled')).toBe('true');
    // QA6-REL-02: moves read as actions, never as the status they lead to.
    expect(screen.getByTestId('move-build_backed_out').textContent).toMatch(/^Move to: /);
    fireEvent.click(screen.getByTestId('move-build_backed_out'));
    const ok = await screen.findByTestId<HTMLButtonElement>('move-ok');
    expect(ok.disabled).toBe(true); // the reason is required
    fireEvent.change(screen.getByTestId('move-reason'), { target: { value: 'Broken build' } });
    fireEvent.click(ok);
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/releases/${REL_ID}/moves`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/releases/${REL_ID}/moves`);
    expect(sent?.body).toMatchObject({
      to_status: 'build_backed_out',
      reason_text: 'Broken build',
    });
    expect(sent?.headers.get('If-Match')).toBe('"7"');
  });

  it('asks only for the fields the move still needs, in the same request', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const fake = api();
    render(<App />);
    // D-155: the next stage's move is the one button; a move within the stage is under More.
    fireEvent.click(await screen.findByTestId('release-more'));
    fireEvent.click(await screen.findByTestId('move-build_completed'));
    const field = await screen.findByTestId('move-field-release_version');
    expect(screen.queryByTestId('move-reason')).toBeNull(); // this move asks for no reason
    fireEvent.change(field, { target: { value: '4.2.0' } });
    fireEvent.click(screen.getByTestId('move-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/releases/${REL_ID}/moves`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/releases/${REL_ID}/moves`);
    expect(sent?.body).toMatchObject({
      to_status: 'build_completed',
      fields: { release_version: '4.2.0' },
    });
  });

  it('REQ-REL-052 AC1: open work is named, and the move goes on only once confirmed', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    let tries = 0;
    const fake = api({
      [`POST /api/v1/releases/${REL_ID}/moves`]: () => {
        tries += 1;
        return tries === 1
          ? {
              status: 409,
              body: problem(409, 'open_work_unconfirmed', {
                params: { count: 1, items: 'CHG-12 Core switch firmware' },
              }),
            }
          : { body: { ...release, version: 8 } };
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('release-more'));
    fireEvent.click(await screen.findByTestId('move-build_completed'));
    fireEvent.change(await screen.findByTestId('move-field-release_version'), {
      target: { value: '4.2.0' },
    });
    fireEvent.click(screen.getByTestId('move-ok'));
    const open = await screen.findByTestId('move-open-work');
    expect(open.textContent).toContain('CHG-12 Core switch firmware');
    expect(screen.getByTestId('move-ok').textContent).toBe('Confirm and continue');
    fireEvent.click(screen.getByTestId('move-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/releases/${REL_ID}/moves`)).toHaveLength(2);
    });
    const [first, second] = fake.find('POST', `/api/v1/releases/${REL_ID}/moves`);
    expect(first?.body).toMatchObject({ confirm_open_work: false });
    expect(second?.body).toMatchObject({ confirm_open_work: true });
  });

  it('REQ-REL-053 AC1: a failed deployment shows its backout plan and "Mark rolled back"', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const failed = { ...release, status: 'deployment_failed', stage: 'deployment' };
    api({
      [`GET /api/v1/releases/${REL_ID}`]: { body: failed, headers: { ETag: '"7"' } },
      [`GET /api/v1/releases/${REL_ID}/stages`]: {
        body: {
          ...panel,
          stage: 'deployment',
          status: 'deployment_failed',
          moves: [
            {
              to_status: 'deployment_rolled_back',
              to_stage: 'deployment',
              reason_mode: 'required',
              reason_list: null,
              required_fields: [],
              allowed: true,
              reason: null,
              missing: [],
            },
          ],
        },
      },
      [`GET /api/v1/releases/${REL_ID}/plan`]: {
        body: [{ section: 'backout', content: '<p>Restore build 4.1.</p>', version: 1 }],
      },
    });
    render(<App />);
    const box = await screen.findByTestId('release-failed');
    expect(box.textContent).toContain('The deployment failed');
    expect((await screen.findByTestId('release-failed-backout')).textContent).toContain(
      'Restore build 4.1.',
    );
    fireEvent.click(screen.getByTestId('release-mark-rolled-back'));
    expect(await screen.findByTestId('move-dialog')).toBeTruthy();
    expect(screen.getByTestId('move-reason')).toBeTruthy(); // the rollback asks for its reason
  });

  it('REQ-REL-053 AC2: a failed release makes its problem, linked, and lists it', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const failed = { ...release, status: 'deployment_failed', stage: 'deployment' };
    const made = {
      id: '01a1a2b3-0000-7000-8000-0000000f0901',
      display_id: 'PRB-3',
      subject: 'Deployment failure: REL-1 Payroll 4.2',
      type: 'problem',
      relation: 'caused_problem',
      status_category: 'open',
    };
    let listed: object[] = [];
    const fake = api(
      {
        [`GET /api/v1/releases/${REL_ID}`]: { body: failed, headers: { ETag: '"7"' } },
        [`GET /api/v1/releases/${REL_ID}/plan`]: { body: [] },
        [`GET /api/v1/releases/${REL_ID}/follow-ups`]: () => ({ body: listed }),
        [`POST /api/v1/releases/${REL_ID}/follow-ups`]: () => {
          listed = [made];
          return { status: 201, body: made };
        },
      },
      ['releases.view', 'releases.create', 'releases.edit', 'problems.create'],
    );
    render(<App />);
    fireEvent.click(await screen.findByTestId('release-create-problem'));
    const title = await screen.findByTestId<HTMLInputElement>('release-follow-up-title');
    expect(title.value).toBe('Deployment failure: REL-1 Payroll 4.2');
    const dialog = await screen.findByTestId('release-follow-up-dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create problem' }));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/releases/${REL_ID}/follow-ups`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/releases/${REL_ID}/follow-ups`);
    expect(sent?.body).toEqual({
      kind: 'problem',
      subject: 'Deployment failure: REL-1 Payroll 4.2',
    });
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect((await screen.findByTestId('release-follow-ups')).textContent).toContain(
      'PRB-3 Deployment failure: REL-1 Payroll 4.2',
    );
  });

  it('REQ-REL-054: a canceled release offers to unlink the changes still in it', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const CHG = '01a1a2b3-0000-7000-8000-00000058b201';
    const canceled = { ...release, status: 'closure_canceled', stage: 'closure' };
    const fake = api({
      [`GET /api/v1/releases/${REL_ID}`]: { body: canceled, headers: { ETag: '"7"' } },
      [`GET /api/v1/releases/${REL_ID}/changes`]: {
        body: [
          {
            id: CHG,
            visible: true,
            display_id: 'CHG-5',
            subject: 'Database upgrade',
            stage: 'implementation',
            status: 'implementation_scheduled',
            status_category: 'open',
          },
          {
            id: '01a1a2b3-0000-7000-8000-00000058b202',
            visible: false,
            display_id: null,
            subject: null,
            stage: null,
            status: null,
            status_category: null,
          },
        ],
      },
      [`DELETE /api/v1/releases/${REL_ID}/changes/${CHG}`]: { status: 204 },
    });
    render(<App />);
    const offer = await screen.findByTestId('release-canceled-changes');
    expect(offer.textContent).toContain('1 change is still in this cancelled release');
    expect(offer.textContent).toContain('CHG-5 Database upgrade');
    fireEvent.click(screen.getByTestId('release-unlink-changes'));
    await waitFor(() => {
      expect(fake.find('DELETE', `/api/v1/releases/${REL_ID}/changes/${CHG}`)).toHaveLength(1);
    });
    // The hidden change is never unlinked from here.
    expect(fake.calls.filter((c) => c.method === 'DELETE')).toHaveLength(1);
  });

  it('the failed panel is absent while the deployment has not failed', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api();
    render(<App />);
    await screen.findByTestId('release-page');
    expect(screen.queryByTestId('release-failed')).toBeNull();
  });

  it('asks for the reason of a rejection and the comment a level requires, then decides', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const fake = api();
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: /Approvals/ }));
    fireEvent.click(await screen.findByTestId(`approval-${APPROVAL_ID}-approve`));
    // comments_required: approving without a comment is not offered.
    const approveOk = screen.getAllByRole('button', { name: 'Approve' }).at(-1);
    expect((approveOk as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    fireEvent.click(screen.getByTestId(`approval-${APPROVAL_ID}-reject`));
    const rejectOk = screen.getAllByRole('button', { name: 'Reject' }).at(-1) as HTMLButtonElement;
    expect(rejectOk.disabled).toBe(true); // a rejection needs its own reason
    fireEvent.change(screen.getByTestId('approval-comment'), {
      target: { value: 'Backout plan missing' },
    });
    fireEvent.click(rejectOk);
    const path = `/api/v1/releases/${REL_ID}/approvals/${APPROVAL_ID}/decision`;
    await waitFor(() => {
      expect(fake.find('POST', path)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', path);
    expect(sent?.body).toMatchObject({ decision: 'reject', comment: 'Backout plan missing' });
    expect(sent?.headers.get('If-Match')).toBe('"2"');
  });

  it('asks for lists and people with their own controls, and names custom fields', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api();
    render(<App />);
    // The Details tab with nothing changed: no footer, so no second primary action (D-155).
    await screen.findByTestId('release-details');
    expect(screen.queryByTestId('release-details-save')).toBeNull();
    fireEvent.click(screen.getByTestId('move-testing_in_progress'));
    const dialog = await screen.findByTestId('move-dialog');
    // The custom field reads by its name, never its key (rule d).
    expect(await within(dialog).findByText('CAB reference')).toBeTruthy();
    expect(within(dialog).queryByText(/cab_ref/)).toBeNull();
    // The release type and the release manager are pickers, not text boxes.
    expect(
      within(screen.getByTestId('move-field-release_type')).getByRole('combobox'),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId('move-field-release_manager_id')).getByRole('combobox'),
    ).toBeTruthy();
  });

  it('QA6-REL-01/02: the pass 2 layout, with a pending approval shown as a status', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api();
    render(<App />);
    expect(await screen.findByTestId('release-properties')).toBeTruthy(); // the end-side panel
    expect(await screen.findByTestId('release-awaiting-approval')).toBeTruthy();
    const visible = screen.getByTestId('release-moves').querySelectorAll('[data-testid^="move-"]');
    expect(visible.length).toBeLessThanOrEqual(3); // beside More: the 4-action rule
  });

  it("D-155: one primary, the next stage's move; the key facts, no chip repeating the stage bar; no empty schedule card", async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api();
    render(<App />);
    const moves = await screen.findByTestId('release-moves');
    const buttons = within(moves)
      .getAllByRole('button')
      .filter((b) => b.getAttribute('data-testid') !== 'release-more');
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual(['move-testing_in_progress']);
    expect(buttons[0]?.textContent).toBe('Move to Testing');
    // A1 on every record: the stage chip and the key facts; never the status twice.
    // No stage chip: the stage bar always shows the stage (QA fix-round D2).
    expect(screen.queryByTestId('release-stage')).toBeNull();
    expect(screen.queryByTestId('release-status')).toBeNull();
    // Worded as every record's menu (QA10V-10: "⋮ More").
    expect(screen.getByTestId('release-more').textContent).toContain('More actions');
    expect(screen.getByTestId('release-people').textContent).toMatch(/^Requested by /);
    expect(screen.getByTestId('record-kind-tile').getAttribute('data-kind')).toBe('release');
  });

  it('D-155: the plan shows the sections of this stage; empty ones are one compact Add list', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const section = (code: string, content: string | null) => ({
      section: code,
      content,
      version: 1,
    });
    api({
      [`GET /api/v1/releases/${REL_ID}/plan`]: {
        body: [
          section('impact', '<p>Mail is down for ten minutes.</p>'),
          section('rollout', null),
          section('backout', null),
          section('review_findings', null),
          section('review_went_well', null),
          section('review_went_badly', null),
        ],
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Plan' }));
    expect(await screen.findByTestId('plan-impact')).toBeDefined(); // written: shown
    const adds = within(screen.getByTestId('release-plan-add')).getAllByRole('button');
    expect(adds.map((b) => b.textContent)).toEqual(['Add rollout plan', 'Add backout plan']);
    expect(screen.queryByTestId('plan-review_findings-add')).toBeNull(); // the build stage
    fireEvent.click(screen.getByTestId('plan-rollout-add'));
    expect(await screen.findByTestId('plan-rollout-editor')).toBeDefined();
  });

  it('D-155: Details shows its footer only with a change; Save says what is missing; zone once', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api();
    render(<App />);
    const details = await screen.findByTestId('release-details');
    expect(within(details).getAllByText(/^Times are in /)).toHaveLength(1);
    expect(within(details).getAllByText('Choose…').length).toBeGreaterThanOrEqual(2);
    fireEvent.change(within(details).getByTestId('release-version'), { target: { value: '5.4' } });
    const footer = await screen.findByTestId('release-details-footer');
    const buttons = within(footer)
      .getAllByRole('button')
      .map((b) => b.textContent);
    expect(buttons).toEqual(['Cancel', 'Save']);
    fireEvent.click(within(footer).getByTestId('release-details-cancel'));
    await waitFor(() => {
      expect(screen.queryByTestId('release-details-footer')).toBeNull();
    });
  });

  it('D-155: downtime on one baseline, the zone said once, and Add says what is missing', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api({ [`GET /api/v1/releases/${REL_ID}/downtimes`]: { body: [] } });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Downtime' }));
    const tab = await screen.findByTestId('release-downtimes');
    expect(await within(tab).findByText('No downtime planned.')).toBeDefined();
    expect(within(tab).getAllByText(/^Times are in /)).toHaveLength(1);
    expect(screen.getByTestId<HTMLButtonElement>('downtime-add').disabled).toBe(true);
    fireEvent.mouseOver(within(tab).getByTestId('disabled-why'));
    expect(await screen.findByText('Choose when it starts and when it ends.')).toBeDefined();
  });

  describe('the Changes tab (WP-058b S1; REQ-REL-033)', () => {
    const CHG = '01a1a2b3-0000-7000-8000-00000058b101';
    const OTHER = '01a1a2b3-0000-7000-8000-00000058b102';
    const inRelease = [
      {
        id: CHG,
        visible: true,
        display_id: 'CHG-5',
        subject: 'Database upgrade',
        stage: 'implementation',
        status: 'implementation_scheduled',
        status_category: 'open',
      },
      {
        id: '01a1a2b3-0000-7000-8000-00000058b103',
        visible: false,
        display_id: null,
        subject: null,
        stage: null,
        status: null,
        status_category: null,
      },
    ];
    const found = {
      items: [
        {
          ...fakeIncident({ id: OTHER, display_id: 'CHG-9', subject: 'Firewall rules' }),
          type: 'change',
        },
      ],
      next_cursor: null,
      has_more: false,
      people: {},
    };

    it('lists its changes, a hidden one by its existence only; refuses one in another release', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      const fake = api({
        [`GET /api/v1/releases/${REL_ID}/changes`]: { body: inRelease },
        'GET /api/v1/changes': { body: found },
        [`POST /api/v1/releases/${REL_ID}/changes`]: {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'change_id',
                code: 'change_in_other_release',
                message_key: 'errors.field.change_in_other_release',
                params: { release: 'REL-3' },
              },
            ],
          }),
        },
      });
      render(<App />);
      fireEvent.click(await screen.findByRole('tab', { name: 'Changes' }));
      const tab = await screen.findByTestId('release-changes');
      expect(await within(tab).findByText('Database upgrade')).toBeDefined();
      expect(within(tab).getByText("A change you can't see")).toBeDefined();
      const box = screen
        .getByTestId('release-change-add')
        .closest('.ant-select')
        ?.querySelector('.ant-select-selector');
      if (box === null || box === undefined) throw new Error('no select');
      fireEvent.mouseDown(box);
      fireEvent.click(await screen.findByTitle('CHG-9 Firewall rules'));
      await waitFor(() => {
        expect(fake.find('POST', `/api/v1/releases/${REL_ID}/changes`)).toHaveLength(1);
      });
      expect(fake.find('POST', `/api/v1/releases/${REL_ID}/changes`)[0]?.body).toEqual({
        change_id: OTHER,
      });
      expect(
        await within(tab).findByText('This change is already in the open release REL-3.'),
      ).toBeDefined();
    });

    it('without releases.edit: no add and no take out', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      api({ [`GET /api/v1/releases/${REL_ID}/changes`]: { body: inRelease } }, ['releases.view']);
      render(<App />);
      fireEvent.click(await screen.findByRole('tab', { name: 'Changes' }));
      const tab = await screen.findByTestId('release-changes');
      await within(tab).findByText('Database upgrade');
      expect(screen.queryByTestId('release-change-add')).toBeNull();
      expect(screen.queryByTestId(`release-change-remove-${CHG}`)).toBeNull();
    });
  });

  it('WP-058b S3: the Stages tab lists the picked stage’s tasks and time, from the current one', async () => {
    const task = (id: string, title: string, stage: string, status: string) => ({
      id,
      work_item_id: REL_ID,
      title,
      description: null,
      owner_id: null,
      group_id: null,
      status,
      priority: 'normal',
      due_at: null,
      done_at: null,
      done_by: null,
      stage,
      position: 0,
      from_plan: false,
      required: false,
      internal: false,
      version: 1,
      created_at: '2027-03-01T00:00:00Z',
      updated_at: '2027-03-01T00:00:00Z',
    });
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api({
      [`GET /api/v1/releases/${REL_ID}/stages`]: {
        body: {
          ...panel,
          rail: panel.rail.map((s) =>
            s.stage === 'build'
              ? { ...s, tasks_done: 1, tasks_total: 2 }
              : { ...s, tasks_done: 0, tasks_total: 0 },
          ),
        },
      },
      [`GET /api/v1/releases/${REL_ID}/tasks`]: {
        body: {
          items: [
            task('t1', 'Tag the build', 'build', 'done'),
            task('t2', 'Freeze the branch', 'build', 'open'),
            task('t3', 'Write the notes', 'testing', 'open'),
          ],
          done: 1,
          total: 3,
        },
      },
      [`GET /api/v1/releases/${REL_ID}/worklogs`]: {
        body: {
          items: [
            {
              id: 'w1',
              owner_id: REL_ID,
              worklog_type: 'fix',
              started_at: '2027-03-01T09:00:00Z',
              ended_at: '2027-03-01T10:30:00Z',
              minutes: 90,
              description: null,
              version: 1,
              created_by: null,
              stage: 'build',
            },
          ],
          minutes: 90,
          by_owner: [],
          by_type: [],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Stages' }));
    const stages = await screen.findByTestId('release-stage-work');
    // The current stage (build) first: its two tasks, one done, and its 90 minutes.
    expect(await within(stages).findByText('Tasks 1 / 2')).toBeDefined();
    expect(within(stages).getByText('Tag the build')).toBeDefined();
    expect(within(stages).queryByText('Write the notes')).toBeNull();
    expect(within(stages).getByTestId('release-stage-worklog-w1')).toBeDefined();
    fireEvent.click(within(stages).getByText('Testing'));
    expect(await within(stages).findByText('Write the notes')).toBeDefined();
    expect(within(stages).queryByText('Tag the build')).toBeNull();
  });

  describe('conflicts on the Schedule tab (WP-058b S2; REQ-REL-040, -041)', () => {
    const FREEZE = '01a1a2b3-0000-7000-8000-00000058c001';
    const OTHER = '01a1a2b3-0000-7000-8000-00000058c002';
    const MANAGER = '01a1a2b3-0000-7000-8000-00000058c003';
    const base = {
      starts_at: '2027-03-06T22:00:00Z',
      ends_at: '2027-03-07T02:00:00Z',
      window_id: null,
      window_name: null,
      window_labels: null,
      record_id: null,
      record_type: null,
      ack: null,
    };
    const conflicts = {
      items: [
        {
          ...base,
          kind: 'freeze',
          blocks: true,
          window_id: FREEZE,
          window_name: 'Quarter close',
          key: 'freeze:f',
        },
        {
          ...base,
          kind: 'overlap',
          blocks: false,
          record_id: OTHER,
          record_type: 'release',
          key: 'overlap:o',
        },
        {
          ...base,
          kind: 'role_booked',
          blocks: false,
          record_id: OTHER,
          record_type: 'release',
          key: 'role_booked:r',
          ack: {
            acked_by: MANAGER,
            acked_at: '2027-03-01T08:00:00Z',
            reason: 'Two engineers on call',
          },
        },
      ],
      passed_window_ids: [],
    };
    const routes = {
      [`GET /api/v1/releases/${REL_ID}/schedule`]: { body: [] },
      [`GET /api/v1/releases/${REL_ID}/conflicts`]: { body: conflicts },
      [`POST /api/v1/releases/${REL_ID}/conflicts/acks`]: { body: { version: 8 } },
      [`POST /api/v1/releases/${REL_ID}/freeze-override`]: { body: { version: 8 } },
      [`GET /api/v1/users/${MANAGER}`]: {
        body: fakeUser({ id: MANAGER, display_name: 'Rania Khan' }),
      },
    };

    it('names another release by type, says who acknowledged what, and acknowledges with a reason', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      const fake = api(routes, ['releases.view', 'releases.edit']);
      render(<App />);
      fireEvent.click(await screen.findByRole('tab', { name: 'Schedule' }));
      const panel = await screen.findByTestId('release-conflicts');
      const overlap = within(panel).getByTestId('release-conflict-overlap');
      expect(overlap.textContent).toContain('At the same time as another release');
      expect(overlap.textContent).toContain('Another release');
      expect(await within(panel).findByText('Rania Khan')).toBeDefined();
      expect(within(panel).getByTestId('release-conflict-acked').textContent).toContain(
        'Two engineers on call',
      );
      // No override without releases.override_freeze; a block is never acknowledged.
      expect(screen.queryByTestId('release-freeze-override')).toBeNull();
      expect(screen.queryByTestId('release-conflict-ack-freeze')).toBeNull();
      fireEvent.click(within(overlap).getByTestId('release-conflict-ack-overlap'));
      fireEvent.change(await screen.findByTestId('release-ack-reason'), {
        target: { value: 'Same team, agreed' },
      });
      fireEvent.click(screen.getByTestId('release-ack-ok'));
      await waitFor(() => {
        expect(fake.find('POST', `/api/v1/releases/${REL_ID}/conflicts/acks`)).toHaveLength(1);
      });
      const [sent] = fake.find('POST', `/api/v1/releases/${REL_ID}/conflicts/acks`);
      expect(sent?.body).toEqual({ key: 'overlap:o', reason: 'Same team, agreed' });
      expect(sent?.headers.get('If-Match')).toBe('"7"');
    });

    it('with releases.override_freeze: passes only the blocking freezes, with a reason', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      const fake = api(routes, ['releases.view', 'releases.edit', 'releases.override_freeze']);
      render(<App />);
      fireEvent.click(await screen.findByRole('tab', { name: 'Schedule' }));
      fireEvent.click(await screen.findByTestId('release-freeze-override'));
      expect((await screen.findByTestId('release-override')).textContent).toContain(
        'only this freeze is passed',
      );
      fireEvent.change(screen.getByTestId('release-override-reason'), {
        target: { value: 'Payroll must go out' },
      });
      fireEvent.click(screen.getByTestId('release-override-ok'));
      await waitFor(() => {
        expect(fake.find('POST', `/api/v1/releases/${REL_ID}/freeze-override`)).toHaveLength(1);
      });
      expect(fake.find('POST', `/api/v1/releases/${REL_ID}/freeze-override`)[0]?.body).toEqual({
        reason: 'Payroll must go out',
        window_ids: [FREEZE],
      });
    });
  });

  it('QA6-REL-04: the tab and the top bar say which release this is', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api();
    render(<App />);
    await screen.findByTestId('release-page');
    await waitFor(() => {
      expect(document.title).toContain('REL-1');
    });
    expect(document.title).toContain('Releases');
  });

  describe('the Workflows tab (WP-048b S4d; REQ-WF-023, -024)', () => {
    const INSTANCE = '01a1a2b3-0000-7000-8000-0000000e0f01';
    const PERMS = ['releases.view', 'releases.edit', 'workflows.run'];
    const failedRun = {
      instance: {
        id: INSTANCE,
        workflow_id: '01a1a2b3-0000-7000-8000-0000000e0f02',
        version_number: 1,
        record_type: 'release',
        record_id: REL_ID,
        status: 'failed',
        failure: { node: 'call', code: 'webhook_timeout', params: {} },
        wake_at: null,
        started_how: 'trigger',
        started_at: '2026-11-11T10:00:00Z',
        finished_at: null,
        stopped_reason: null,
        version: 4,
      },
      workflow_name: 'Release go-live',
      definition: {
        format: 1,
        nodes: [
          { id: 'start', type: 'start', config: {}, position: { x: 0, y: 0 } },
          { id: 'call', type: 'webhook', config: {}, position: { x: 0, y: 140 } },
          { id: 'end', type: 'end', config: {}, position: { x: 0, y: 280 } },
        ],
        links: [
          { from: 'start', port: 'next', to: 'call' },
          { from: 'call', port: 'next', to: 'end' },
        ],
        variables: [],
      },
      current_nodes: ['call'],
      steps: [
        {
          seq: 1,
          node: 'start',
          node_type: 'start',
          result: 'next',
          at: '2026-11-11T10:00:00Z',
          detail: null,
        },
        {
          seq: 2,
          node: 'call',
          node_type: 'webhook',
          result: 'set:retried',
          at: '2026-11-11T10:00:07Z',
          detail: null,
        },
      ],
    };

    it('shows the run: the failure in words, the path, and the log to the second; Retry carries the If-Match', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      const fake = api(
        {
          [`GET /api/v1/automation/workflows/records/release/${REL_ID}`]: { body: [failedRun] },
          [`POST /api/v1/automation/workflows/instances/${INSTANCE}/retry`]: {
            body: { ...failedRun.instance, status: 'running', version: 5 },
          },
        },
        PERMS,
      );
      render(<App />);
      fireEvent.click(await screen.findByRole('tab', { name: 'Workflows' }));
      const failure = await screen.findByTestId(`record-workflow-failure-${INSTANCE}`);
      expect(failure.textContent).toContain('Stopped at the step Webhook');
      expect(failure.textContent).toContain('The other side took too long to answer.');
      expect(failure.textContent).not.toContain('webhook_timeout'); // never a raw code
      const log = screen.getByTestId(`record-workflow-log-${INSTANCE}`);
      expect(log.textContent).toContain('7 s'); // start → call, to the second
      expect(log.textContent).not.toContain('set:retried');
      fireEvent.click(screen.getByTestId(`record-workflow-retry-${INSTANCE}`));
      await waitFor(() => {
        expect(
          fake.find('POST', `/api/v1/automation/workflows/instances/${INSTANCE}/retry`),
        ).toHaveLength(1);
      });
      expect(
        fake
          .find('POST', `/api/v1/automation/workflows/instances/${INSTANCE}/retry`)[0]
          ?.headers.get('If-Match'),
      ).toBe('"4"');
    });

    it('REQ-REL-021 AC1: a failed step shows on the header, with Retry and a way to the tab', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      const fake = api(
        {
          [`GET /api/v1/automation/workflows/records/release/${REL_ID}`]: { body: [failedRun] },
          [`POST /api/v1/automation/workflows/instances/${INSTANCE}/retry`]: {
            body: { ...failedRun.instance, status: 'running', version: 5 },
          },
        },
        PERMS,
      );
      render(<App />);
      const banner = await screen.findByTestId('workflow-failure-banner');
      expect(banner.textContent).toContain(failedRun.workflow_name);
      expect(banner.textContent).toContain('call');
      fireEvent.click(within(banner).getByTestId('workflow-failure-retry'));
      await waitFor(() => {
        expect(
          fake.find('POST', `/api/v1/automation/workflows/instances/${INSTANCE}/retry`),
        ).toHaveLength(1);
      });
      fireEvent.click(within(banner).getByTestId('workflow-failure-open'));
      expect(await screen.findByTestId('record-workflows')).toBeDefined();
    });

    it('without workflows.run there is no banner', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      api(
        { [`GET /api/v1/automation/workflows/records/release/${REL_ID}`]: { body: [failedRun] } },
        ['releases.view', 'releases.edit'],
      );
      render(<App />);
      await screen.findByTestId('release-page');
      expect(screen.queryByTestId('workflow-failure-banner')).toBeNull();
    });

    it('REQ-WF-024 AC2: Skip asks first, then goes with the run’s If-Match', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      const fake = api(
        {
          [`GET /api/v1/automation/workflows/records/release/${REL_ID}`]: { body: [failedRun] },
          [`POST /api/v1/automation/workflows/instances/${INSTANCE}/skip`]: {
            body: { ...failedRun.instance, status: 'finished', version: 5 },
          },
        },
        PERMS,
      );
      render(<App />);
      fireEvent.click(await screen.findByRole('tab', { name: 'Workflows' }));
      fireEvent.click(await screen.findByTestId(`record-workflow-skip-${INSTANCE}`));
      const dialog = await screen.findByRole('dialog');
      expect(dialog.textContent).toContain('Skip the step Webhook?');
      expect(dialog.textContent).toContain('recorded with your name');
      fireEvent.click(within(dialog).getByRole('button', { name: 'Skip this step' }));
      await waitFor(() => {
        expect(
          fake.find('POST', `/api/v1/automation/workflows/instances/${INSTANCE}/skip`),
        ).toHaveLength(1);
      });
      expect(
        fake
          .find('POST', `/api/v1/automation/workflows/instances/${INSTANCE}/skip`)[0]
          ?.headers.get('If-Match'),
      ).toBe('"4"');
    });

    it('REQ-WF-023 AC3: no Workflows tab without workflows.run', async () => {
      window.history.pushState({}, '', `/releases/${REL_ID}`);
      api({}, ['releases.view', 'releases.edit']);
      render(<App />);
      await screen.findByRole('tab', { name: 'Details' });
      expect(screen.queryByRole('tab', { name: 'Workflows' })).toBeNull();
    });
  });
});

describe('console: releases by stage (WP-058b S5b)', () => {
  const toTesting = {
    to_status: 'testing_in_progress',
    to_stage: 'testing',
    reason_mode: 'none',
    reason_list: null,
    required_fields: [],
    allowed: true,
    reason: null,
    missing: [],
  };

  async function moveTo(stage: string) {
    fireEvent.click(await screen.findByTestId(`release-board-move-${REL_ID}`));
    const menus = await screen.findAllByRole('menu');
    const menu = menus.at(-1);
    if (menu === undefined) throw new Error('no menu');
    fireEvent.click(within(menu).getByText(stage));
  }

  it('REQ-REL-056: a release sits in its stage; moving it opens its own move dialog', async () => {
    window.history.pushState({}, '', '/releases/board');
    api({ [`GET /api/v1/releases/${REL_ID}/stages`]: { body: { ...panel, moves: [toTesting] } } });
    render(<App />);
    const build = await screen.findByTestId('release-board-column-build');
    expect(await within(build).findByText('REL-1')).toBeTruthy();
    await moveTo('Testing');
    expect(await screen.findByTestId('move-dialog')).toBeTruthy();
  });

  it('REQ-REL-056 AC1: a stage it cannot reach is refused in words and the card stays', async () => {
    window.history.pushState({}, '', '/releases/board');
    api();
    render(<App />);
    const build = await screen.findByTestId('release-board-column-build');
    await within(build).findByText('REL-1');
    await moveTo('Deployment');
    await waitFor(() => {
      expect(screen.getByTestId('release-board-refusal').textContent).toContain(
        'cannot move to Deployment',
      );
    });
    expect(within(build).getByText('REL-1')).toBeTruthy();
    expect(screen.queryByTestId('move-dialog')).toBeNull();
  });
});
