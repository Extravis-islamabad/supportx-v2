import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-049b s1 (REQ-AST-032 AC3): booking ahead from the portal, only when the organisation
// allows it.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ME = fakeSession({ user_type: 'requester', roles: ['requester'] });
const ASSET = '01900000-0000-7000-8000-00000000d901';
const BOOKING = {
  id: 'bk-7',
  asset_id: ASSET,
  borrower_id: ME.user.id,
  department_id: null,
  starts_at: '2026-12-01T09:00:00Z',
  ends_at: '2026-12-01T17:00:00Z',
  status: 'booked',
  loan_id: null,
  channel: 'portal',
  comment: null,
  version: 2,
};

function portal(routes: Record<string, unknown>) {
  const fake = fakeApi({
    'GET /api/v1/auth/me': { body: ME },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    'GET /api/v1/assets/mine': { body: [] },
    ...routes,
  });
  restore = fake.restore;
  return fake;
}

describe('portal: bookings', () => {
  it('shows nothing about booking while the organisation has not allowed it', async () => {
    window.history.pushState({}, '', '/my-assets');
    const fake = portal({
      'GET /api/v1/assets/my-bookings': { body: { enabled: false, bookings: [], assets: {} } },
    });
    render(<App />);
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/assets/my-bookings')).toHaveLength(1);
    });
    expect(await screen.findByTestId('my-assets')).toBeTruthy();
    expect(screen.queryByTestId('my-bookings')).toBeNull();
  });

  it('lists my bookings by asset and cancels one with If-Match', async () => {
    window.history.pushState({}, '', '/my-assets');
    const fake = portal({
      'GET /api/v1/assets/my-bookings': {
        body: { enabled: true, bookings: [BOOKING], assets: { [ASSET]: 'AST-9' } },
      },
      'POST /api/v1/assets/my-bookings/bk-7/cancel': { body: { ...BOOKING, status: 'cancelled' } },
    });
    render(<App />);
    const mine = await screen.findByTestId('my-booking-bk-7');
    expect(within(mine).getByText('AST-9')).toBeTruthy();
    expect(screen.getByTestId('my-booking-new-open').textContent).toBe('Book an asset');
    fireEvent.click(within(mine).getByTestId('my-booking-cancel-bk-7'));
    const confirm = await screen.findByRole('tooltip');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Yes, cancel it' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/my-bookings/bk-7/cancel')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/assets/my-bookings/bk-7/cancel');
    expect(sent?.headers.get('If-Match')).toBe('"2"');
  });

  it('the booking dialog says what is still missing while it cannot be sent', async () => {
    window.history.pushState({}, '', '/my-assets');
    portal({
      'GET /api/v1/assets/my-bookings': { body: { enabled: true, bookings: [], assets: {} } },
      'GET /api/v1/assets/bookable': { body: [] },
    });
    render(<App />);
    expect(await screen.findByText('You have no bookings ahead.')).toBeTruthy();
    fireEvent.click(screen.getByTestId('my-booking-new-open'));
    const dialog = await screen.findByTestId('my-booking-new');
    const why = await within(dialog).findByTestId('my-booking-why');
    expect(why.textContent).toBe('Choose the asset to book.');
    const ok = within(dialog).getByRole('button', { name: 'Book an asset' });
    expect(ok.hasAttribute('disabled')).toBe(true);
    expect(ok.getAttribute('aria-describedby')).toBe('my-booking-why');
  });
});
