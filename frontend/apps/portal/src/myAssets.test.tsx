import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from './App';

// WP-049a s4 (REQ-AST-023, 024): My assets in the portal, for requesters with no asset rights.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ME = fakeSession({ user_type: 'requester', roles: ['requester'] });
const LAPTOP = {
  id: '01900000-0000-7000-8000-00000000d101',
  tag: 'AST-41',
  name: 'Field laptop',
  product_type_id: '01900000-0000-7000-8000-00000000c001',
  state_id: '01900000-0000-7000-8000-00000000a001',
  through_department: false,
  acknowledgement: {
    id: 'k-1',
    status: 'pending',
    comment: null,
    channel: null,
    answered_at: null,
    asked_at: '2026-11-06T08:00:00Z',
  },
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

describe('portal: my assets', () => {
  it('a loaned asset says when it is due back, in red once that has passed', async () => {
    window.history.pushState({}, '', '/my-assets');
    const later = { ...LAPTOP, acknowledgement: null, loan_due_at: '2999-01-01T09:00:00Z' };
    const late = {
      ...later,
      id: 'late-1',
      name: 'Projector',
      loan_due_at: '2020-01-01T09:00:00Z',
      loan_overdue: true,
    };
    portal({ 'GET /api/v1/assets/mine': { body: [later, late] } });
    render(<App />);
    const due = await screen.findByTestId(`my-asset-due-${LAPTOP.id}`);
    expect(due.textContent).toMatch(/^Due back /);
    expect(due.getAttribute('data-tone')).toBe('warning');
    expect(screen.getByTestId('my-asset-due-late-1').getAttribute('data-tone')).toBe('error');
  });

  it('lists what I hold; accepting answers once, a dispute needs a comment', async () => {
    window.history.pushState({}, '', '/my-assets');
    const fake = portal({
      'GET /api/v1/assets/mine': { body: [LAPTOP] },
      'POST /api/v1/assets/acknowledgements/k-1/answer': {
        body: { ...LAPTOP.acknowledgement, status: 'disputed', channel: 'portal' },
      },
    });
    render(<App />);
    const row = await screen.findByTestId(`my-asset-${LAPTOP.id}`);
    expect(within(row).getByText('Field laptop')).toBeTruthy();
    expect(within(row).getByText('Waiting for you')).toBeTruthy();
    fireEvent.click(within(row).getByTestId(`my-asset-dispute-${LAPTOP.id}`));
    const dialog = await screen.findByTestId('my-assets-dispute');
    const send = within(dialog).getByRole('button', { name: 'Something is wrong' });
    expect(send.hasAttribute('disabled')).toBe(true); // a dispute says what is wrong
    fireEvent.change(within(dialog).getByTestId('my-assets-dispute-comment'), {
      target: { value: 'The screen is cracked' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Something is wrong' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/acknowledgements/k-1/answer')).toHaveLength(1);
    });
    const [call] = fake.find('POST', '/api/v1/assets/acknowledgements/k-1/answer');
    expect(call?.body).toEqual({
      accept: false,
      comment: 'The screen is cracked',
      channel: 'portal',
    });
  });

  it('a newly given asset shows without a refresh', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/my-assets');
    let rows: unknown[] = [];
    portal({ 'GET /api/v1/assets/mine': () => ({ body: rows }) });
    render(<App />);
    expect(await screen.findByText('You hold no assets.')).toBeTruthy();
    rows = [LAPTOP];
    act(() => {
      realtime.publish(`:user:${ME.user.id}`, { type: 'assets.mine_changed', ids: [LAPTOP.id] });
    });
    expect(await screen.findByTestId(`my-asset-${LAPTOP.id}`)).toBeTruthy();
  });
});
