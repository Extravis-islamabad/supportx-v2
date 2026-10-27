import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { AccountSecurity, MfaRole, UserDetail } from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeSession, fakeUser } from '../../../test/api';

// WP-039 session 3: MFA policy (REQ-SEC-024), My account (REQ-SEC-028), MFA reset (REQ-SEC-025).

let restore: () => void = () => undefined;
type Routes = NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']>;
const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });

function api(routes: Routes, me = ADMIN) {
  const fake = consoleApi({ me, routes });
  restore = fake.restore;
  return fake;
}
afterEach(() => {
  restore();
});

function role(overrides: Partial<MfaRole>): MfaRole {
  return {
    role_id: 'r-tech',
    key: 'technician',
    name: 'technician',
    mode: 'required',
    is_default: true,
    holders: 4,
    enrolled: 3,
    version: 0,
    ...overrides,
  };
}

const SECURITY: AccountSecurity = {
  has_password: true,
  mfa_mode: 'required',
  mfa_enrolled: false,
  mfa_due_at: '2026-11-04T10:00:00Z',
  recovery_codes: false,
  recent_sign_ins: [
    { at: '2026-10-28T08:00:00Z', outcome: 'success', method: 'password' },
    { at: '2026-10-27T08:00:00Z', outcome: 'failed', method: 'password' },
  ],
  details_available: true,
};

describe('MFA policy (Admin › Sign-in and security)', () => {
  it('shows each role with its enrolment count; a mode is saved with If-Match', async () => {
    window.history.pushState({}, '', '/admin/security');
    const fake = api({
      'GET /api/v1/identity/sso': { body: { items: [] } },
      'GET /api/v1/identity/invitations': { body: { items: [] } },
      'GET /api/v1/identity/mfa': {
        body: {
          grace_days: 7,
          roles: [
            role({}),
            role({
              role_id: 'r-req',
              key: 'requester',
              mode: 'optional',
              holders: 10,
              enrolled: 1,
            }),
          ],
        },
      },
      'PUT /api/v1/identity/mfa/roles/r-req': {
        body: role({ role_id: 'r-req', key: 'requester', mode: 'required', version: 1 }),
      },
    });
    render(<App />);
    const card = await screen.findByTestId('security-mfa');
    expect((await within(card).findByTestId('security-mfa-count-technician')).textContent).toBe(
      '3 of 4',
    );
    fireEvent.click(
      within(within(card).getByTestId('security-mfa-mode-requester')).getByText('Required'),
    );
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/mfa/roles/r-req')).toHaveLength(1);
    });
    const [put] = fake.find('PUT', '/api/v1/identity/mfa/roles/r-req');
    expect(put?.body).toEqual({ mode: 'required' });
    expect(put?.headers.get('If-Match')).toBe('"0"');
  });
});

describe('My account (REQ-SEC-028)', () => {
  it('opens without any code, shows how I sign in, and its changes go to the sign-in service', async () => {
    window.history.pushState({}, '', '/profile');
    api({ 'GET /api/v1/account/security': { body: SECURITY } });
    render(<App />);
    expect((await screen.findByTestId('account-mfa-state')).textContent).toContain('Required by');
    const card = screen.getByTestId('account-security');
    expect(within(card).getByTestId('account-change-password').getAttribute('href')).toBe(
      '/api/v1/auth/account-action?action=password&returnTo=%2Fprofile',
    );
    expect(within(card).getByTestId('account-set-up-mfa').getAttribute('href')).toContain(
      'action=mfa',
    );
    expect(within(card).getByTestId('account-recent').textContent).toContain('Failed');
    expect(screen.queryByTestId('mfa-reminder')).toBeNull(); // not on this very page
  });

  it('says what happened when the sign-in service sends me back, then tidies the address', async () => {
    window.history.pushState({}, '', '/profile?account_action=mfa&status=success');
    api({
      'GET /api/v1/account/security': {
        body: { ...SECURITY, mfa_enrolled: true, mfa_due_at: null },
      },
    });
    render(<App />);
    expect(await screen.findByText('Two-step sign-in is set up.')).toBeDefined();
    expect(window.location.search).toBe('');
  });

  it('a person who signs in through single sign-on has no password to change', async () => {
    window.history.pushState({}, '', '/profile');
    api({
      'GET /api/v1/account/security': {
        body: { ...SECURITY, has_password: false, mfa_mode: 'off', mfa_due_at: null },
      },
    });
    render(<App />);
    await screen.findByTestId('account-mfa-state');
    const card = screen.getByTestId('account-security');
    expect(within(card).queryByTestId('account-change-password')).toBeNull();
    expect(card.textContent).toContain('single sign-on');
  });
});

describe('MFA reminder', () => {
  it('shows the due date with a button to set it up, everywhere but My account', async () => {
    window.history.pushState({}, '', '/');
    api({}, { ...ADMIN, mfa_due_at: '2026-11-04T10:00:00Z' });
    render(<App />);
    const reminder = await screen.findByTestId('mfa-reminder');
    expect(reminder.textContent).toContain('Your organisation requires two-step sign-in');
    expect(within(reminder).getByTestId('mfa-reminder-set-up').getAttribute('href')).toContain(
      'action=mfa',
    );
  });
});

describe('MFA reset on a person (REQ-SEC-025)', () => {
  const PERSON: UserDetail = fakeUser({
    id: 'u-9',
    display_name: 'Ina Vitee',
    email: 'ina@acme.test',
    signed_in_before: true,
    version: 2,
  });

  it('an admin resets someone else after a confirmation', async () => {
    window.history.pushState({}, '', '/admin/users');
    const fake = api({
      'GET /api/v1/access-settings': {
        body: { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 },
      },
      'GET /api/v1/users': { body: { items: [PERSON], has_more: false, next_cursor: null } },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/users/u-9': { body: PERSON, headers: { ETag: '"2"' } },
      'POST /api/v1/identity/people/u-9/reset-mfa': { status: 204 },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Ina Vitee'));
    fireEvent.click(await screen.findByTestId('person-reset-mfa'));
    const popup = await waitFor(() => {
      const shown = document.querySelector<HTMLElement>('.ant-popconfirm');
      if (shown === null) throw new Error('no confirmation open');
      return shown;
    });
    expect(popup.textContent).toContain('Check who is asking first');
    fireEvent.click(within(popup).getByRole('button', { name: 'Reset two-step sign-in' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/people/u-9/reset-mfa')).toHaveLength(1);
    });
  });
});
