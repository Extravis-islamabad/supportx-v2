import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';

// WP-032 D6 (REQ-PRT-008): approve several at once, after a confirmation that names them all.

const ME = fakeSession({
  display_name: 'Omar Manager',
  user_type: 'requester',
  roles: ['requester'],
});
const REQUESTER = '01a1a2b3-0000-7000-8000-00000000b201';

function pending(n: number, extra: Record<string, unknown> = {}) {
  return {
    approval_id: `01a1a2b3-0000-7000-8000-0000000a000${String(n)}`,
    approval_version: 1,
    record_id: `01a1a2b3-0000-7000-8000-0000000c000${String(n)}`,
    display_id: `SR-${String(n)}`,
    subject: `Laptop ${String(n)}`,
    requester_id: REQUESTER,
    on_behalf_of_id: null,
    catalog_item_id: null,
    comments_required: false,
    created_at: '2026-11-05T08:00:00Z',
    origin: 'named',
    state: 'pending',
    decided_at: null,
    ...extra,
  };
}

let restore: () => void = () => undefined;

describe('portal approvals inbox (WP-032)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/approvals');
  });
  afterEach(() => {
    restore();
  });

  it('approves three at once with one comment, after naming them', async () => {
    const fake = fakeApi({
      'GET /api/v1/auth/me': { body: ME },
      'GET /api/v1/entitlements': { body: fakeEntitlements() },
      'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
      'GET /api/v1/service-requests/my-approvals': {
        body: {
          items: [pending(1), pending(2), pending(3, { origin: 'backup' })],
          people: { [REQUESTER]: { display_name: 'Sara', email: 'sara@example.com' } },
        },
      },
      'GET /api/v1/service-requests/my-approvals/decided': { body: { items: [], people: {} } },
      'POST /api/v1/service-requests/approvals/decisions': {
        body: {
          items: [1, 2, 3].map((n) => ({
            approval_id: pending(n).approval_id,
            record_id: pending(n).record_id,
            decided: true,
            code: null,
          })),
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('portal-approval-delegated-SR-3')).toBeDefined();
    // QA10-P2-06: what is asked opens read-only before deciding.
    expect(screen.getByTestId('portal-approval-open-SR-3').getAttribute('href')).toBe(
      `/service-requests/${pending(3).record_id}`,
    );
    fireEvent.click(screen.getByTestId('portal-approvals-pick-all'));
    fireEvent.click(screen.getByTestId('portal-approvals-approve-picked'));
    const named = await screen.findByTestId('portal-approvals-confirm-list');
    for (const id of ['SR-1', 'SR-2', 'SR-3']) expect(within(named).getByText(id)).toBeDefined();
    fireEvent.change(screen.getByTestId('portal-bulk-comment'), {
      target: { value: 'Budget approved' },
    });
    fireEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: 'Approve 3 requests' }),
    );
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/service-requests/approvals/decisions')).toHaveLength(1);
    });
    const sent = fake.find('POST', '/api/v1/service-requests/approvals/decisions')[0]?.body as {
      items: unknown[];
      comment: string;
    };
    expect(sent.comment).toBe('Budget approved');
    expect(sent.items).toHaveLength(3);
  });
});
