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

function api() {
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

  it('shows the rail, says why a move is not possible, and asks for the reason a move needs', async () => {
    window.history.pushState({}, '', `/releases/${REL_ID}`);
    const fake = api();
    render(<App />);
    expect(await screen.findByTestId('release-rail')).toBeTruthy();
    expect(screen.getByTestId('rail-build').textContent).toContain('Build');
    expect(screen.getByTestId<HTMLButtonElement>('move-closure_canceled').disabled).toBe(true);
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
});
