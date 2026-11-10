import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeCustomField, fakeIncident, fakeSession } from '@supportx/api-client/testing';

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
) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['tenant_admin'] },
      {
        permissions: ['releases.view', 'releases.create', 'releases.edit'].map((key) => ({
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
    await screen.findByTestId('release-row-REL-1');
    const bar = screen.getByTestId('releases-filters');
    expect(within(bar).getByTestId('releases-view')).toBeTruthy();
    expect(within(bar).getByTestId('releases-search')).toBeTruthy();
    const first = fake.find('GET', '/api/v1/releases')[0];
    expect(first?.url.searchParams.get('view')).toBe('open');
    expect(first?.url.searchParams.get('include_total')).toBe('true');
    fireEvent.click(within(bar).getByText('All'));
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
    // The Details tab with nothing changed: its Save is not a second primary action.
    const save = await screen.findByTestId('release-details-save');
    expect(save.className).not.toContain('ant-btn-primary');
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

  it("D-155: one primary, the next stage's move; no chips repeating the stage bar; no empty schedule card", async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    api();
    render(<App />);
    const moves = await screen.findByTestId('release-moves');
    const buttons = within(moves)
      .getAllByRole('button')
      .filter((b) => b.getAttribute('data-testid') !== 'release-more');
    expect(buttons.map((b) => b.getAttribute('data-testid'))).toEqual(['move-testing_in_progress']);
    expect(buttons[0]?.textContent).toBe('Move to Testing');
    expect(screen.queryByTestId('release-stage')).toBeNull();
    expect(screen.queryByTestId('release-status')).toBeNull();
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
});
