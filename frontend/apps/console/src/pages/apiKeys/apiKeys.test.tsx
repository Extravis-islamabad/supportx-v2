import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { ApiKey, ApiKeyRules } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { scopesOf } from './scopes';

// WP-041 (D-128): Admin › API keys and My profile › API keys.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });
const ME = ADMIN.user.id;
const RULES: ApiKeyRules = {
  may_create: true,
  manages_keys: true,
  never_expires_allowed: false,
  default_lifetime_days: 90,
  max_lifetime_days: 366,
};
const KEY: ApiKey = {
  id: '01900000-0000-7000-8000-00000000a001',
  name: 'Nightly export',
  owner_id: ME,
  owner_name: 'Amal Admin',
  scopes: ['incidents:read', 'incidents:write', 'users:read'],
  last_four: 'x9Qa',
  expires_at: '2027-02-01T00:00:00Z',
  ip_allowlist: [],
  last_used_at: null,
  last_used_ip: null,
  revoked_at: null,
  created_at: '2026-11-03T08:00:00Z',
  status: 'active',
};
const SCOPES = ['incidents', 'users'].flatMap((area) =>
  (['read', 'write'] as const).map((access) => ({ code: `${area}:${access}`, area, access })),
);
const IDENTITY = {
  console_idle_seconds: 3600,
  console_absolute_seconds: 43200,
  portal_idle_seconds: 1800,
  portal_absolute_seconds: 43200,
  create_people_on_sign_in: true,
  people_may_create_keys: false,
  allow_non_expiring_keys: false,
  version: 3,
};

function api(routes: Record<string, unknown>, me = ADMIN) {
  const fake = consoleApi({
    me,
    routes: {
      'GET /api/v1/api-keys/rules': { body: RULES },
      'GET /api/v1/api-keys/scopes': { body: SCOPES },
      'GET /api/v1/api-keys': { body: [KEY] },
      'GET /api/v1/identity/settings': { body: IDENTITY },
      'GET /api/v1/api-keys/owners': { body: [] },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('scopes from the form', () => {
  it('read gives the read scope; read and write gives both; none gives nothing', () => {
    expect(scopesOf({ incidents: 'write', users: 'read', sla: 'none' })).toEqual([
      'incidents:read',
      'incidents:write',
      'users:read',
    ]);
  });
});

describe('Admin › API keys', () => {
  it('lists keys with labels only, never a scope code or the secret', async () => {
    window.history.pushState({}, '', '/admin/api-keys');
    api({});
    render(<App />);
    const panel = await screen.findByTestId('api-keys-admin');
    expect(await within(panel).findByText('Nightly export')).toBeDefined();
    expect(within(panel).getByText('Ends in x9Qa')).toBeDefined();
    expect(within(panel).getByText('Not used yet')).toBeDefined();
    expect(within(panel).getByText('Active')).toBeDefined();
    expect(panel.textContent).not.toMatch(/incidents:|users:|api_key_status/);
    // The rules sit above the list for whoever may change sign-in settings.
    expect(await screen.findByTestId('api-key-rules')).toBeDefined();
  });

  it('makes a key with the chosen scopes and shows its text once', async () => {
    window.history.pushState({}, '', '/admin/api-keys');
    const text = `sxk_${'0'.repeat(26)}_${'1'.repeat(26)}_${'a'.repeat(43)}`;
    const fake = api({
      'POST /api/v1/api-keys': { status: 201, body: { ...KEY, key: text } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('api-key-new-open'));
    const dialog = await screen.findByTestId('api-key-new');
    fireEvent.change(within(dialog).getByTestId('api-key-name'), {
      target: { value: 'Nightly export' },
    });
    const incidents = within(dialog).getByTestId('api-key-scope-incidents');
    fireEvent.click(within(incidents).getByText('read and write'));
    fireEvent.click(within(dialog).getByTestId('api-key-create'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/api-keys')).toHaveLength(1);
    });
    const [call] = fake.find('POST', '/api/v1/api-keys');
    const body = call?.body as { scopes: string[]; owner_id: string | null };
    expect(body.scopes).toEqual(['incidents:read', 'incidents:write']);
    expect(body.owner_id).toBeNull(); // "Me": the server makes it the caller's own key
    const shown = await screen.findByTestId('api-key-shown');
    expect(within(shown).getByTestId<HTMLInputElement>('api-key-text').value).toBe(text);
    fireEvent.click(within(shown).getByTestId('api-key-shown-done'));
    await waitFor(() => {
      expect(screen.queryByTestId('api-key-text')).toBeNull();
    });
  });

  it('offers the service identities as owners, from their own list (PEO-14)', async () => {
    window.history.pushState({}, '', '/admin/api-keys');
    const fake = api({
      'GET /api/v1/api-keys/owners': {
        body: [{ id: '01900000-0000-7000-8000-00000000b001', display_name: 'Jira connector' }],
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('api-key-new-open'));
    const dialog = await screen.findByTestId('api-key-new');
    const owner = within(dialog).getByTestId('api-key-owner');
    const opener = owner.querySelector('.ant-select-selector') ?? owner;
    fireEvent.mouseDown(opener);
    expect(await screen.findByText('Jira connector')).toBeTruthy();
    expect(fake.find('GET', '/api/v1/api-keys/owners').length).toBeGreaterThan(0);
    // Never through the people list, which refuses service identities (they are not people).
    expect(fake.find('GET', '/api/v1/users')).toHaveLength(0);
  });

  it('refuses to send a key with no scope', async () => {
    window.history.pushState({}, '', '/admin/api-keys');
    const fake = api({});
    render(<App />);
    fireEvent.click(await screen.findByTestId('api-key-new-open'));
    const dialog = await screen.findByTestId('api-key-new');
    fireEvent.change(within(dialog).getByTestId('api-key-name'), { target: { value: 'Empty' } });
    fireEvent.click(within(dialog).getByTestId('api-key-create'));
    expect(await within(dialog).findByText('Choose at least one scope.')).toBeDefined();
    expect(fake.find('POST', '/api/v1/api-keys')).toHaveLength(0);
  });

  it('revokes after a confirmation', async () => {
    window.history.pushState({}, '', '/admin/api-keys');
    const fake = api({
      [`POST /api/v1/api-keys/${KEY.id}/revoke`]: { body: { ...KEY, status: 'revoked' } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('api-key-revoke-x9Qa'));
    const confirm = await screen.findByRole('dialog', { name: /Revoke the key “Nightly export”/ });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Revoke' }));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/api-keys/${KEY.id}/revoke`)).toHaveLength(1);
    });
  });
});

describe('My profile › API keys', () => {
  const TECH = fakeSession();

  it('is not shown when the organisation does not let people make keys and they have none', async () => {
    window.history.pushState({}, '', '/profile');
    api(
      {
        'GET /api/v1/api-keys/rules': {
          body: { ...RULES, may_create: false, manages_keys: false },
        },
        'GET /api/v1/api-keys': { body: [] },
        [`GET /api/v1/users/${TECH.user.id}`]: { body: { id: TECH.user.id } },
      },
      TECH,
    );
    render(<App />);
    await waitFor(() => {
      expect(document.querySelector('[data-testid="api-keys-mine"]')).toBeNull();
    });
  });

  it('shows one’s own keys and the button when allowed', async () => {
    window.history.pushState({}, '', '/profile');
    api(
      {
        'GET /api/v1/api-keys/rules': { body: { ...RULES, manages_keys: false } },
        'GET /api/v1/api-keys': { body: [{ ...KEY, owner_id: TECH.user.id }] },
      },
      TECH,
    );
    render(<App />);
    const panel = await screen.findByTestId('api-keys-mine');
    expect(await within(panel).findByText('Nightly export')).toBeDefined();
    expect(within(panel).getByTestId('api-key-new-open')).toBeDefined();
    expect(within(panel).queryByText('Owner')).toBeNull();
  });
});
