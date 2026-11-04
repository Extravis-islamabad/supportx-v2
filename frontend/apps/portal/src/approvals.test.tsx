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

  it('a service request: its answers, its steps (an internal one unnamed), and withdraw', async () => {
    const ITEM = '01a1a2b3-0000-7000-8000-00000000c001';
    const me = fakeSession({ user_type: 'requester', roles: ['requester'] });
    window.history.pushState({}, '', `/service-requests/${RECORD}`);
    const withdraw = `/api/v1/service-requests/${RECORD}/withdraw`;
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/auth/me': { body: me },
      [`GET /api/v1/portal/service-requests/${RECORD}`]: {
        body: {
          id: RECORD,
          display_id: 'SR-7',
          subject: 'Laptop for Sara',
          portal_status: 'awaiting_approval',
          reach: 'own',
          requester_id: me.user.id,
          on_behalf_of_id: null,
          catalog_item_id: ITEM,
          answers: { model: 'air' },
          approval_status: 'pending',
          created_at: '2026-11-04T08:00:00Z',
          updated_at: '2026-11-04T08:00:00Z',
          resolution: null,
          version: 4,
        },
      },
      [`GET /api/v1/portal/service-requests/${RECORD}/steps`]: {
        body: {
          items: [
            { position: 1, title: 'Order the laptop', done: true },
            { position: 2, title: null, done: false },
          ],
          done: 1,
          total: 2,
        },
      },
      [`GET /api/v1/service-requests/${RECORD}/approvals`]: { body: { items: [], people: {} } },
      [`GET /api/v1/catalog/items/${ITEM}`]: {
        body: {
          id: ITEM,
          names: { en: 'New laptop' },
          questions: [{ key: 'model', label: { en: 'Model' }, kind: 'choice', required: true }],
        },
      },
      [`POST ${withdraw}`]: { body: { id: RECORD, status: 'canceled', version: 5 } },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('portal-status')).textContent).toBe('Waiting for approval');
    await waitFor(() => {
      expect(screen.getByTestId('portal-service-request-answers').textContent).toContain('air');
    });
    const steps = await screen.findByTestId('portal-service-request-steps');
    expect(within(steps).getByText('Order the laptop')).toBeDefined();
    expect(within(steps).getByText('Step 2 of 2')).toBeDefined();
    fireEvent.click(screen.getByTestId('portal-withdraw'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Withdraw request' }));
    await waitFor(() => {
      expect(fake.find('POST', withdraw)).toHaveLength(1);
    });
    expect(fake.find('POST', withdraw)[0]?.headers.get('If-Match')).toBe('"4"');
  });

  it('a fulfilled request asks the requester to confirm receipt (REQ-SR-059)', async () => {
    const me = fakeSession({ user_type: 'requester', roles: ['requester'] });
    window.history.pushState({}, '', `/service-requests/${RECORD}`);
    const confirm = `/api/v1/portal/service-requests/${RECORD}/resolution/confirm`;
    let confirmed = false;
    const fulfilled = {
      id: RECORD,
      display_id: 'SR-7',
      subject: 'Laptop for Sara',
      portal_status: 'resolved',
      reach: 'own',
      requester_id: me.user.id,
      on_behalf_of_id: null,
      catalog_item_id: null,
      answers: {},
      approval_status: 'approved',
      created_at: '2026-11-04T08:00:00Z',
      updated_at: '2026-11-04T09:00:00Z',
      resolution: '<p>Order the laptop</p>',
      version: 6,
    };
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/auth/me': { body: me },
      [`GET /api/v1/portal/service-requests/${RECORD}`]: () => ({
        body: confirmed ? { ...fulfilled, portal_status: 'closed', version: 7 } : fulfilled,
      }),
      [`GET /api/v1/portal/service-requests/${RECORD}/steps`]: {
        body: { items: [], done: 0, total: 0 },
      },
      [`GET /api/v1/service-requests/${RECORD}/approvals`]: { body: { items: [], people: {} } },
      [`POST ${confirm}`]: () => {
        confirmed = true;
        return { body: { ...fulfilled, portal_status: 'closed', version: 7 } };
      },
    });
    restore = fake.restore;
    render(<App />);
    const receipt = await screen.findByTestId('portal-receipt');
    expect(receipt.textContent).toContain('Order the laptop');
    fireEvent.click(within(receipt).getByTestId('portal-receipt-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', confirm)).toHaveLength(1);
    });
    await waitFor(() => {
      expect(screen.getByTestId('portal-status').textContent).toBe('Closed');
    });
  });
});
