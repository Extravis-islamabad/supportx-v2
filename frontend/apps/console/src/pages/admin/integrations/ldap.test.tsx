import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { LdapDirectory } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi, problem } from '../../../test/api';

// WP-040 (D-118): Admin › Integrations › Directories, the AD/LDAP part.
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const PAGE = '/admin/integrations/directories';
const ENTRA = '/api/v1/integrations/directories';
const LDAP = '/api/v1/integrations/ldap-directories';
const GROUPS = '/api/v1/organization/groups';
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

function ldap(over: Partial<LdapDirectory> = {}): LdapDirectory {
  return {
    id: 'ldap-1',
    name: 'Corp AD',
    settings: { host: 'dc1.corp.example', security: 'ldaps', vendor: 'ad', port: 636 },
    bind_password: { secret_type: 'password', set_at: '2026-11-03T09:00:00Z' },
    enabled: true,
    federation_state: 'failed',
    federation_error: 'ldap_federation_refused',
    people: 12,
    version: 2,
    ...over,
  };
}

describe('Admin › Integrations › Directories › AD/LDAP', () => {
  afterEach(() => {
    restore();
    setDefaultClientFactory(inertClientFactory);
  });

  it('shows each directory with its connection state and why it failed', async () => {
    window.history.pushState({}, '', PAGE);
    api({
      me: ADMIN,
      routes: {
        [`GET ${ENTRA}`]: { body: [] },
        [`GET ${GROUPS}`]: { body: [] },
        [`GET ${LDAP}`]: { body: [ldap()] },
      },
    });
    render(<App />);
    const row = (await screen.findByText('Corp AD')).closest('tr');
    if (row === null) throw new Error('a row');
    expect(within(row).getByText('Not connected')).toBeTruthy();
    expect(row.textContent).toContain('The identity service refused the directory settings');
    expect(row.textContent).toContain('LDAPS (encrypted from the start)');
  });

  it('says why AD/LDAP is not available here, with no add button', async () => {
    window.history.pushState({}, '', PAGE);
    api({
      me: ADMIN,
      routes: {
        [`GET ${ENTRA}`]: { body: [] },
        [`GET ${GROUPS}`]: { body: [] },
        [`GET ${LDAP}`]: { status: 503, body: problem(503, 'ldap_federation_not_installed') },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('ldap-off')).textContent).toContain(
      'AD/LDAP is not turned on for this installation',
    );
    expect(screen.queryByTestId('ldap-add')).toBeNull();
  });

  it('saves plain LDAP only after the explicit choice, and the password once', async () => {
    window.history.pushState({}, '', PAGE);
    const fake = api({
      me: ADMIN,
      routes: {
        [`GET ${ENTRA}`]: { body: [] },
        [`GET ${GROUPS}`]: { body: [] },
        [`GET ${LDAP}`]: { body: [] },
        [`POST ${LDAP}`]: { status: 201, body: ldap({ federation_state: 'pending' }) },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('ldap-add'));
    const fill = (id: string, value: string) => {
      fireEvent.change(screen.getByTestId(id), { target: { value } });
    };
    fill('ldap-name', 'Lab LDAP');
    fill('ldap-host', 'ldap.lab.example');
    fill('ldap-bind_dn', 'CN=svc,DC=lab,DC=example');
    fill('ldap-bind_password', 'pw-made-in-this-test');
    fill('ldap-users_dn', 'OU=People,DC=lab,DC=example');
    fireEvent.click(screen.getByLabelText('Not encrypted'));
    const save = screen.getByTestId('ldap-save');
    expect(save.hasAttribute('disabled')).toBe(true); // not without the choice
    fireEvent.click(screen.getByTestId('ldap-allow-plain'));
    expect(save.hasAttribute('disabled')).toBe(false);
    fireEvent.click(save);
    await waitFor(() => {
      expect(fake.find('POST', LDAP)).toHaveLength(1);
    });
    expect(fake.find('POST', LDAP)[0]?.body).toMatchObject({
      name: 'Lab LDAP',
      security: 'plain',
      allow_plain: true,
      bind_password: 'pw-made-in-this-test',
      groups_dn: null,
      changed_sync_seconds: 1800,
    });
  });
});
