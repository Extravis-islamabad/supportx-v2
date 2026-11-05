import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeSession } from '@supportx/api-client/testing';

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
      'GET /api/v1/releases/settings': { body: { closure_codes: [], own_lists: {} } },
      [`POST /api/v1/releases/${REL_ID}/moves`]: { body: { ...release, version: 8 } },
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
});
