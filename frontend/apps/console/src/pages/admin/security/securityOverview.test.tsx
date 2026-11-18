import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { SecurityOverview } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-057 S4d: the security overview at the top of Admin › Sign-in and security.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ roles: ['tenant_admin'] });

const OVERVIEW: SecurityOverview = {
  sso_required: 'technicians',
  sso_setups: 1,
  sso_expiry_days_left: 5,
  mfa: { roles: 3, roles_required: 1, holders: 12, enrolled: 9 },
  password_min_length: 8,
  password_breached_check: true,
  console_idle_seconds: 3600,
  console_absolute_seconds: 43200,
  network_rules: { console: 0, portal: 0, api: 2 },
  keys: { active: 4, out_of_policy: 2, unused: 1 },
  service_accounts: 3,
  service_accounts_without_owner: 1,
  seal_states: { sealed: 2, sealing: 1 },
  key_since: '2026-10-01T08:00:00Z',
  failed_sign_ins: 6,
  locked_sign_ins: 1,
  data_region: null,
  flags: [
    { code: 'sso_credential_expires_soon', area: 'sign_in', severity: 'high', count: 5 },
    { code: 'password_short', area: 'passwords', severity: 'medium', count: 8 },
    { code: 'keys_unused', area: 'keys', severity: 'low', count: 1 },
  ],
  recommendations: {
    password_min_length: 12,
    password_breached_check: true,
    console_idle_seconds: 3600,
    console_absolute_seconds: 43200,
    key_max_lifetime_days: 366,
    allow_non_expiring_keys: false,
    sso_expiry_warn_days: 30,
    sso_expiry_urgent_days: 7,
  },
  tiles_hidden: [],
};

function api(overview: SecurityOverview = OVERVIEW) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/identity/security-overview': { body: overview },
      'GET /api/v1/identity/settings': { body: {} },
      'GET /api/v1/identity/sso': { body: { items: [] } },
      'GET /api/v1/identity/invitations': { body: { items: [] } },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('Admin › Sign-in and security › Security at a glance', () => {
  it('shows each area as a tile, by label and number, never a code', async () => {
    window.history.pushState({}, '', '/admin/security');
    api();
    render(<App />);
    const card = await screen.findByTestId('security-overview');
    expect(await within(card).findByTestId('security-tile-mfa')).toBeDefined();
    expect(within(card).getByTestId('security-tile-mfa').textContent).toContain('9 / 12');
    expect(within(card).getByTestId('security-tile-keys').textContent).toContain(
      'Outside the policy: 2 · Unused: 1',
    );
    expect(within(card).getByTestId('security-tile-sign_in').textContent).toContain(
      'For technicians',
    );
    expect(within(card).getByTestId('security-tile-sign_in_events').textContent).toContain('6');
    // No code reaches the screen (rule 5d).
    expect(card.textContent).not.toMatch(
      /sso_credential|password_short|keys_unused|sign_in_events/,
    );
  });

  it('lists the flags most severe first, in words, each leading to its detail', async () => {
    window.history.pushState({}, '', '/admin/security');
    api();
    render(<App />);
    const flags = await screen.findByTestId('security-flags');
    const items = within(flags).getAllByRole('listitem');
    expect(items[0]?.textContent).toContain('Act now');
    expect(items[0]?.textContent).toContain('runs out soon. Days left: 5');
    expect(items[1]?.textContent).toContain('shorter than 12 characters. Minimum now: 8');
    expect(items[2]?.textContent).toContain('Consider');
    expect(within(flags).getByTestId('security-flag-open-keys_unused').textContent).toBe(
      'Open API keys',
    );
  });

  it('hides the data region when it is blank and shows it when the installation sets it', async () => {
    window.history.pushState({}, '', '/admin/security');
    api();
    const first = render(<App />);
    await screen.findByTestId('security-tile-mfa');
    expect(screen.queryByTestId('security-tile-region')).toBeNull();
    first.unmount();
    restore();
    api({ ...OVERVIEW, data_region: 'KSA, Riyadh' });
    render(<App />);
    expect((await screen.findByTestId('security-tile-region')).textContent).toContain(
      'KSA, Riyadh',
    );
  });

  it('says so when nothing is weaker than recommended', async () => {
    window.history.pushState({}, '', '/admin/security');
    api({ ...OVERVIEW, flags: [] });
    render(<App />);
    expect((await screen.findByTestId('security-flags-none')).textContent).toBe(
      'Nothing here is weaker than recommended.',
    );
  });

  it('leaves out the tiles the viewer may not open (no key or sign-in rights)', async () => {
    window.history.pushState({}, '', '/admin/security');
    api({
      ...OVERVIEW,
      keys: null,
      service_accounts: null,
      service_accounts_without_owner: null,
      failed_sign_ins: null,
      locked_sign_ins: null,
      tiles_hidden: ['keys', 'service_accounts', 'sign_in_events'],
      flags: [],
    });
    render(<App />);
    await screen.findByTestId('security-tile-mfa');
    expect(screen.queryByTestId('security-tile-keys')).toBeNull();
    expect(screen.queryByTestId('security-tile-service_accounts')).toBeNull();
    expect(screen.queryByTestId('security-tile-sign_in_events')).toBeNull();
  });
});
