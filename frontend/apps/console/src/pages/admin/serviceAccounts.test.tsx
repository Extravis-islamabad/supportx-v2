import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { ApiKey, ServiceAccount } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-057 S4a: Admin › Service accounts (REQ-SEC-036) and the key policy (REQ-SEC-037).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });
const ACCOUNT: ServiceAccount = {
  id: '01900000-0000-7000-8000-0000000005a1',
  name: 'Nightly sync',
  description: 'Pulls tickets into the data lake',
  owner_id: ADMIN.user.id,
  owner_name: 'Amal Admin',
  managed_here: true,
  needs_new_owner: true,
  active: true,
  keys: 2,
  roles: [{ id: 'r1', key: 'technician', name: 'Technician', system: true }],
  version: 4,
};
const CONNECTOR: ServiceAccount = {
  ...ACCOUNT,
  id: '01900000-0000-7000-8000-0000000005a2',
  name: 'Entra directory',
  description: null,
  owner_id: null,
  owner_name: null,
  managed_here: false,
  needs_new_owner: false,
  keys: 0,
  roles: [],
};
const IDENTITY = {
  console_idle_seconds: 3600,
  console_absolute_seconds: 43200,
  portal_idle_seconds: 1800,
  portal_absolute_seconds: 43200,
  create_people_on_sign_in: true,
  invitation_valid_days: 7,
  password_min_length: 12,
  password_upper: true,
  password_lower: true,
  password_digits: true,
  password_special: true,
  password_history: 5,
  password_expiry_days: 0,
  password_breached_check: true,
  mfa_grace_days: 7,
  people_edit_contact: false,
  people_may_create_keys: false,
  allow_non_expiring_keys: false,
  key_max_lifetime_days: 366,
  keys_require_ip_range: false,
  key_unused_days: 90,
  password_policy_editable: true,
  password_policy_state: 'default',
  password_policy_error: null,
  version: 3,
};
const KEY: ApiKey = {
  id: '01900000-0000-7000-8000-00000000a001',
  name: 'Nightly export',
  owner_id: ACCOUNT.id,
  owner_name: 'Nightly sync',
  scopes: ['incidents:read'],
  last_four: 'x9Qa',
  expires_at: '2027-09-01T00:00:00Z',
  ip_allowlist: [],
  last_used_at: null,
  last_used_ip: null,
  revoked_at: null,
  created_at: '2026-01-03T08:00:00Z',
  status: 'active',
  out_of_policy: ['lifetime_over_policy', 'no_ip_range'],
  unused: true,
};

function api(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/service-accounts': { body: [ACCOUNT, CONNECTOR] },
      'GET /api/v1/identity/settings': { body: IDENTITY },
      'GET /api/v1/api-keys': { body: [KEY] },
      'GET /api/v1/api-keys/rules': {
        body: {
          may_create: true,
          manages_keys: true,
          never_expires_allowed: false,
          default_lifetime_days: 90,
          max_lifetime_days: 366,
        },
      },
      'GET /api/v1/api-keys/scopes': { body: [] },
      'GET /api/v1/api-keys/owners': { body: [] },
      'GET /api/v1/api-keys/policy-impact': {
        body: { keys: 3, lifetime_over_policy: 2, no_ip_range: 1 },
      },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('Admin › Service accounts', () => {
  it('lists accounts by name with their owner, a hand-over flag and no codes', async () => {
    window.history.pushState({}, '', '/admin/service-accounts');
    api();
    render(<App />);
    const table = await screen.findByTestId('service-accounts-table');
    expect(await within(table).findByText('Nightly sync')).toBeDefined();
    expect(within(table).getByText('Amal Admin')).toBeDefined();
    expect(within(table).getByTestId(`service-account-handover-${ACCOUNT.id}`).textContent).toBe(
      'Needs a new owner',
    );
    expect(within(table).getByText('A connector or workflow identity')).toBeDefined();
    expect(table.textContent).not.toMatch(/technician|managed_here|needs_new_owner/);
  });

  it('keeps Save off for a new account until it has an owner', async () => {
    window.history.pushState({}, '', '/admin/service-accounts');
    api();
    render(<App />);
    fireEvent.click(await screen.findByTestId('service-account-new'));
    const drawer = await screen.findByTestId('service-account-drawer');
    fireEvent.change(within(drawer).getByTestId('service-account-name'), {
      target: { value: 'Nightly sync' },
    });
    // The save stays off until an owner is chosen (the server also refuses without one).
    expect(within(document.body).getByTestId('service-account-save').hasAttribute('disabled')).toBe(
      true,
    );
  });
});

describe('Admin › API keys › Key policy', () => {
  it('says how many keys a stricter policy would flag before it is saved', async () => {
    window.history.pushState({}, '', '/admin/api-keys');
    const fake = api({ 'PUT /api/v1/identity/settings': { body: { ...IDENTITY, version: 4 } } });
    render(<App />);
    const card = await screen.findByTestId('api-key-policy');
    const lifetime = within(card).getByTestId('api-key-policy-lifetime');
    fireEvent.change(lifetime, { target: { value: '90' } });
    await waitFor(() => {
      expect(within(card).getByTestId('api-key-policy-impact').textContent).toBe(
        '3 existing keys would be flagged as out of policy. They keep working until you revoke them.',
      );
    });
    fireEvent.click(within(card).getByTestId('api-key-policy-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/settings')).toHaveLength(1);
    });
    expect(fake.find('PUT', '/api/v1/identity/settings')[0]?.body).toEqual({
      key_max_lifetime_days: 90,
      keys_require_ip_range: false,
      key_unused_days: 90,
    });
  });

  it('flags a key that breaks the policy and one unused, by label', async () => {
    window.history.pushState({}, '', '/admin/api-keys');
    api();
    render(<App />);
    expect(
      (await screen.findByTestId(`api-key-gap-${KEY.id}-lifetime_over_policy`)).textContent,
    ).toBe('Lasts longer than the policy allows');
    expect(screen.getByTestId(`api-key-gap-${KEY.id}-no_ip_range`).textContent).toBe('No IP range');
    expect(screen.getByTestId(`api-key-unused-${KEY.id}`).textContent).toBe('Unused');
  });
});
