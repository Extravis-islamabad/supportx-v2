import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from './App';

// WP-045d S4a (REQ-CHG-109): a requester follows the changes they raised, live, and an
// approver decides a change from the portal's approvals (AC3).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ME = fakeSession({ user_type: 'requester', roles: ['requester'] });
const ID = '01900000-0000-7000-8000-00000000e101';
const CHANGE = {
  id: ID,
  display_id: 'CHG-7',
  subject: 'Move the team printer',
  stage: 'submission',
  status: 'submission_awaiting_acceptance',
  status_category: 'open',
  reach: 'own',
  requester_id: ME.user.id,
  on_behalf_of_id: null,
  created_at: '2026-11-10T08:00:00Z',
  updated_at: '2026-11-10T08:00:00Z',
  version: 2,
  planned_start: null,
  planned_end: null,
};

function portal(routes: Record<string, unknown>) {
  const fake = fakeApi({
    'GET /api/v1/auth/me': { body: ME },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    ...routes,
  });
  restore = fake.restore;
  return fake;
}

describe('portal: my changes', () => {
  it('lists my changes with their stage and status', async () => {
    window.history.pushState({}, '', '/changes');
    portal({
      'GET /api/v1/portal/changes': {
        body: { items: [CHANGE], next_cursor: null, has_more: false },
      },
    });
    render(<App />);
    const card = await screen.findByTestId('portal-change-CHG-7');
    expect(within(card).getByText('Submission')).toBeDefined();
    expect(within(card).getByRole('link').getAttribute('href')).toBe(`/changes/${ID}`);
  });

  it('shows where a change stands and its planned window, refreshed live', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', `/changes/${ID}`);
    let shown: Record<string, unknown> = CHANGE;
    portal({
      [`GET /api/v1/portal/changes/${ID}`]: () => ({ body: shown }),
      [`GET /api/v1/portal/changes/${ID}/conversation`]: { body: { items: [] } },
    });
    render(<App />);
    expect((await screen.findByTestId('portal-change-planned')).textContent).toBe(
      'Not scheduled yet',
    );
    shown = {
      ...CHANGE,
      stage: 'implementation',
      status: 'implementation_in_progress',
      planned_start: '2026-12-05T20:00:00Z',
      planned_end: '2026-12-05T22:00:00Z',
      version: 5,
    };
    act(() => {
      realtime.publish(`:portal_wi:${ID}`, {
        type: 'work_items.portal_changed',
        ids: [ID],
        fields: ['planned_end', 'planned_start', 'stage'],
        version: 5,
      });
    });
    await waitFor(() => {
      expect(screen.getByTestId('portal-change-stage').textContent).toBe('Implementation');
    });
    expect(screen.getByTestId('portal-change-planned').querySelectorAll('time')).toHaveLength(2);
    // Nothing staff-side is on the page (AC2): no plan, risk or approvals section.
    expect(screen.queryByText(/backout|risk/i)).toBeNull();
  });
});

describe('portal approvals: changes (REQ-CHG-109 AC3)', () => {
  it('decides a change approval through the change route', async () => {
    window.history.pushState({}, '', '/approvals');
    const approval = {
      approval_id: '01900000-0000-7000-8000-00000000a201',
      approval_version: 3,
      record_id: ID,
      display_id: 'CHG-7',
      subject: 'Move the team printer',
      requester_id: ME.user.id,
      on_behalf_of_id: null,
      catalog_item_id: null,
      comments_required: false,
      created_at: '2026-11-10T08:00:00Z',
      origin: 'named',
      state: 'pending',
      decided_at: null,
    };
    const decision = `POST /api/v1/changes/${ID}/approvals/${approval.approval_id}/decision`;
    const fake = portal({
      'GET /api/v1/service-requests/my-approvals': { body: { items: [], people: {} } },
      'GET /api/v1/service-requests/my-approvals/decided': { body: { items: [], people: {} } },
      'GET /api/v1/changes/my-approvals': { body: { items: [approval], people: {} } },
      [decision]: { body: { ...approval, state: 'approved' } },
    });
    render(<App />);
    const row = await screen.findByTestId('portal-approval-CHG-7');
    expect(within(row).getByTestId('portal-approval-change-CHG-7')).toBeDefined();
    fireEvent.click(within(row).getByRole('button', { name: 'Approve' }));
    fireEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Approve' }),
    );
    await waitFor(() => {
      expect(
        fake.find('POST', `/api/v1/changes/${ID}/approvals/${approval.approval_id}/decision`),
      ).toHaveLength(1);
    });
    const [sent] = fake.find(
      'POST',
      `/api/v1/changes/${ID}/approvals/${approval.approval_id}/decision`,
    );
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });
});
