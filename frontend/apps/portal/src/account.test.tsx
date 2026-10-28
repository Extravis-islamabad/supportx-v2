import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-039 session 3 (REQ-SEC-028): requesters have My account in the portal too.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('portal: my account', () => {
  it('the user menu opens it; password and two-step sign-in are there', async () => {
    window.history.pushState({}, '', '/');
    const fake = fakeApi({
      'GET /api/v1/auth/me': {
        body: fakeSession({ user_type: 'requester', roles: ['requester'] }),
      },
      'GET /api/v1/entitlements': { body: fakeEntitlements() },
      'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
      'GET /api/v1/account/security': {
        body: {
          has_password: true,
          mfa_mode: 'optional',
          mfa_enrolled: false,
          mfa_due_at: null,
          recovery_codes: false,
          recent_sign_ins: [],
          details_available: true,
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('user-menu'));
    fireEvent.click(await screen.findByText('My profile'));
    await waitFor(() => {
      expect(window.location.pathname).toBe('/account');
    });
    expect(await screen.findByTestId('account-change-password')).toBeDefined();
    expect(screen.getByTestId('account-set-up-mfa').getAttribute('href')).toContain(
      'returnTo=%2Faccount',
    );
  });
});
