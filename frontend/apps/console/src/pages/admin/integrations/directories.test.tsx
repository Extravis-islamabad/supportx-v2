import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { Directory } from '@supportx/api-client';
import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-040 session 2: Admin › Integrations › Directories (REQ-INT-063, REQ-INT-064).
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const BASE = '/api/v1/integrations/directories';
const GROUPS = '/api/v1/organization/groups';
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

function directory(over: Partial<Directory> = {}): Directory {
  return {
    id: 'dir-1',
    name: 'Acme Entra',
    source: 'entra',
    directory_tenant: 'acme.onmicrosoft.com',
    client_id: '11111111-2222-3333-4444-555555555555',
    credential_kind: 'secret',
    secret: { secret_type: 'client_secret', ending: 'a3f9', set_at: '2026-11-01T09:00:00Z' },
    scope: 'all_users',
    scope_groups: [],
    group_mappings: [],
    mapping: {},
    interval_minutes: 30,
    enabled: true,
    people: 42,
    last_synced_at: '2026-11-02T09:00:00Z',
    next_sync_at: '2026-11-02T09:30:00Z',
    last_skips: { guest: 2, unknown_site: 1 },
    version: 3,
    ...over,
  };
}

describe('Admin › Integrations › Directories', () => {
  afterEach(() => {
    restore();
    setDefaultClientFactory(inertClientFactory);
  });

  it('lists each directory with its people and what it skipped, and why', async () => {
    window.history.pushState({}, '', '/admin/integrations/directories');
    api({
      me: ADMIN,
      routes: { [`GET ${BASE}`]: { body: [directory()] }, [`GET ${GROUPS}`]: { body: [] } },
    });
    render(<App />);
    const row = (await screen.findByText('Acme Entra')).closest('tr');
    if (row === null) throw new Error('a row');
    expect(row.textContent).toContain('42');
    expect(row.textContent).toContain('2 × Guest of the directory');
    expect(row.textContent).toContain('1 × Site not in SupportX');
  });

  it('adds a directory with a write-only secret and the separate sync app', async () => {
    window.history.pushState({}, '', '/admin/integrations/directories');
    const fake = api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: { body: [] },
        [`GET ${GROUPS}`]: { body: [] },
        [`POST ${BASE}`]: { status: 201, body: directory() },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('directory-add'));
    expect(screen.getByText(/User\.Read\.All and GroupMember\.Read\.All only/)).toBeTruthy();
    fireEvent.change(screen.getByTestId('directory-name'), { target: { value: 'Acme Entra' } });
    fireEvent.change(screen.getByTestId('directory-directory_tenant'), {
      target: { value: 'acme.onmicrosoft.com' },
    });
    fireEvent.change(screen.getByTestId('directory-client_id'), {
      target: { value: '11111111-2222-3333-4444-555555555555' },
    });
    fireEvent.change(screen.getByTestId('directory-credential'), { target: { value: 's3cret' } });
    fireEvent.click(screen.getByTestId('directory-save'));
    await waitFor(() => {
      expect(fake.find('POST', BASE)).toHaveLength(1);
    });
    expect(fake.find('POST', BASE)[0]?.body).toMatchObject({
      name: 'Acme Entra',
      credential: 's3cret',
      scope: 'all_users',
    });
    // Left empty: the tenant's default applies on the server (D-041).
    expect(fake.find('POST', BASE)[0]?.body).not.toHaveProperty('interval_minutes');
  });

  it('keeps the stored secret when changing other settings', async () => {
    window.history.pushState({}, '', '/admin/integrations/directories');
    const fake = api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: { body: [directory()] },
        [`GET ${GROUPS}`]: { body: [] },
        [`PUT ${BASE}/dir-1`]: { body: directory({ version: 4 }) },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('directory-edit-dir-1'));
    expect(screen.getByText('Stored, ending in ..a3f9. Leave empty to keep it.')).toBeTruthy();
    fireEvent.click(screen.getByTestId('directory-save'));
    await waitFor(() => {
      expect(fake.find('PUT', `${BASE}/dir-1`)).toHaveLength(1);
    });
    expect(fake.find('PUT', `${BASE}/dir-1`)[0]?.body).not.toHaveProperty('credential');
  });

  it('shows a finished sync without a reload, in Arabic right to left', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/admin/integrations/directories');
    let rows = [directory({ people: 42 })];
    const fake = api({
      me: fakeSession({ roles: ['tenant_admin', 'technician'], locale: 'ar' }),
      routes: { [`GET ${BASE}`]: () => ({ body: rows }), [`GET ${GROUPS}`]: { body: [] } },
    });
    render(<App />);
    await screen.findByText('Acme Entra');
    await waitFor(() => {
      expect(document.documentElement.getAttribute('dir')).toBe('rtl');
    });
    rows = [directory({ people: 43 })];
    const before = fake.find('GET', BASE).length;
    act(() => {
      realtime.publish(':broadcast', { type: 'integrations.directories_changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', BASE).length).toBeGreaterThan(before);
    });
    const row = (await screen.findByText('Acme Entra')).closest('tr');
    if (row === null) throw new Error('a row');
    await waitFor(() => {
      expect(within(row).getByText('43')).toBeTruthy();
    });
  });
});
