import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-030: a requester-only approver decides in the portal (REQ-SR-022 AC2), from the inbox or
// from an e-mail link whose token travels only in the request body.

const RECORD = '01a1a2b3-0000-7000-8000-00000000c501';
const APPROVAL = '01a1a2b3-0000-7000-8000-00000000a001';
const PERSON = '01a1a2b3-0000-7000-8000-0000000000bb';
const TOKEN = 'A'.repeat(21) + '-_' + 'z'.repeat(20);
const BASE = {
  'GET /api/v1/auth/me': { body: fakeSession({ user_type: 'requester', roles: ['requester'] }) },
  'GET /api/v1/entitlements': { body: fakeEntitlements() },
  'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
};
const WAITING = {
  items: [
    {
      approval_id: APPROVAL,
      approval_version: 1,
      record_id: RECORD,
      display_id: 'SR-7',
      subject: 'Laptop for Sara',
      requester_id: PERSON,
      on_behalf_of_id: null,
      catalog_item_id: null,
      comments_required: false,
      created_at: '2026-11-04T08:00:00Z',
    },
  ],
  people: { [PERSON]: { display_name: 'Sara Requester', email: 'sara@example.com' } },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('portal: approvals', () => {
  it('lists what waits for me and approves with If-Match', async () => {
    window.history.pushState({}, '', '/approvals');
    const decision = `/api/v1/service-requests/${RECORD}/approvals/${APPROVAL}/decision`;
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/service-requests/my-approvals': { body: WAITING },
      [`POST ${decision}`]: { body: {} },
    });
    restore = fake.restore;
    render(<App />);
    const row = await screen.findByTestId('portal-approval-SR-7');
    expect(within(row).getByText('For Sara Requester', { exact: false })).toBeDefined();
    fireEvent.click(within(row).getByRole('button', { name: 'Approve' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));
    await waitFor(() => {
      expect(fake.find('POST', decision)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', decision);
    expect(sent?.body).toEqual({ decision: 'approve', comment: null, private: false });
    expect(sent?.headers.get('If-Match')).toBe('"1"');
  });

  it('decides from an e-mail link: the token from the fragment, never in a URL', async () => {
    window.history.pushState({}, '', `/requests/approval-link#${TOKEN}`);
    const fake = fakeApi({
      ...BASE,
      'POST /api/v1/action-links/peek': {
        body: {
          action: 'service_request.approval',
          object_type: 'work_item_approval',
          object_id: APPROVAL,
          expires_at: '2026-11-07T08:00:00Z',
          summary: { display_id: 'SR-7', subject: 'Laptop for Sara', comments_required: false },
        },
      },
      'POST /api/v1/action-links/use': { body: { state: 'rejected', record_id: RECORD } },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('approval-link-summary')).textContent).toContain('SR-7');
    expect(window.location.hash).toBe('');
    const reject = screen.getByTestId('approval-link-reject');
    expect((reject as HTMLButtonElement).disabled).toBe(true); // a rejection needs a reason
    fireEvent.change(screen.getByTestId('approval-link-comment'), {
      target: { value: 'Not this quarter' },
    });
    fireEvent.click(reject);
    await screen.findByTestId('approval-link-done');
    const [used] = fake.find('POST', '/api/v1/action-links/use');
    expect(used?.body).toEqual({
      token: TOKEN,
      body: { decision: 'reject', comment: 'Not this quarter', private: false },
    });
    expect(used?.url.toString()).not.toContain(TOKEN);
  });
});
