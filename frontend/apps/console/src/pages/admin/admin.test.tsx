import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { PermissionInfo, RoleDetail, RoleSummary } from '@supportx/api-client';

import { App } from '../../App';
import { consoleApi, fakeSession, fakeUser, problem } from '../../test/api';

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

const CATALOGUE: PermissionInfo[] = [
  {
    key: 'requests.view',
    module: 'requests',
    feature: 'incident',
    scopes: ['all', 'site', 'group', 'own'],
    entitled: true,
    conditions_supported: false,
  },
  {
    key: 'changes.approve',
    module: 'changes',
    feature: 'change',
    scopes: ['all', 'site', 'group'],
    entitled: false,
    conditions_supported: false,
  },
  {
    key: 'users.view',
    module: 'users',
    feature: null,
    scopes: ['all', 'site', 'group', 'own'],
    entitled: true,
    conditions_supported: true,
  },
];
const HR: RoleSummary = {
  id: 'r-hr',
  key: 'custom_abc',
  name: 'HR desk',
  description: 'People team',
  is_system: false,
  user_count: 2,
  version: 4,
};
const TECH: RoleSummary = {
  id: 'r-tech',
  key: 'technician',
  name: 'technician',
  description: null,
  is_system: true,
  user_count: 3,
  version: 1,
};
const ROLES: RoleSummary[] = [
  {
    id: 'r-admin',
    key: 'tenant_admin',
    name: 'tenant_admin',
    description: null,
    is_system: true,
    user_count: 1,
    version: 1,
  },
  TECH,
  HR,
];
const TECH_DETAIL: RoleDetail = {
  ...TECH,
  permissions: [{ permission: 'requests.view', scope: 'all', condition: null }],
};

function adminRoutes(extra: Parameters<typeof consoleApi>[0] = {}) {
  return api({
    me: ADMIN,
    ...extra,
    routes: {
      'GET /api/v1/permissions': { body: CATALOGUE },
      'GET /api/v1/roles': { body: ROLES },
      'GET /api/v1/roles/r-tech': { body: TECH_DETAIL, headers: { ETag: '"1"' } },
      ...extra.routes,
    },
  });
}

describe('Admin › Roles', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/roles');
  });
  afterEach(() => {
    restore();
  });

  it('lists system roles by their labels and custom roles by name', async () => {
    adminRoutes();
    render(<App />);
    const table = await screen.findByTestId('roles-table');
    expect(await within(table).findByText('Tenant administrator')).toBeDefined();
    expect(within(table).getByText('HR desk')).toBeDefined();
    expect(within(table).getAllByText('Built-in')).toHaveLength(2);
    expect(within(table).queryByText('tenant_admin')).toBeNull(); // never the code
  });

  it('builds a role from the permission matrix; locked permissions cannot be chosen', async () => {
    const fake = adminRoutes({
      routes: {
        'POST /api/v1/roles': { status: 201, body: { ...HR, permissions: [] } },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('new-role'));
    fireEvent.change(await screen.findByTestId('role-name'), { target: { value: 'Site viewer' } });
    const scope = within(await screen.findByTestId('scope-requests.view')).getByRole('combobox');
    fireEvent.mouseDown(scope);
    fireEvent.click(await screen.findByTitle('Their sites'));
    // changes.approve is outside the plan: shown with a lock, its selector disabled.
    expect(screen.getByLabelText('Not in your plan')).toBeDefined();
    expect(
      within(screen.getByTestId('scope-changes.approve'))
        .getByRole('combobox')
        .hasAttribute('disabled'),
    ).toBe(true);
    fireEvent.click(screen.getByTestId('save-role'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/roles')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/roles')[0]?.body).toEqual({
      name: 'Site viewer',
      description: null,
      permissions: [{ permission: 'requests.view', scope: 'site', condition: null }],
    });
    expect(fake.find('POST', '/api/v1/roles')[0]?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('opens built-in roles read-only', async () => {
    adminRoutes();
    render(<App />);
    fireEvent.click(await screen.findByTestId('role-row-technician'));
    expect(await screen.findByText(/Built-in roles cannot be changed/)).toBeDefined();
    expect(screen.queryByTestId('save-role')).toBeNull();
  });

  it('explains a refused escalation', async () => {
    adminRoutes({
      routes: { 'POST /api/v1/roles': { status: 403, body: problem(403, 'privilege_escalation') } },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('new-role'));
    fireEvent.change(await screen.findByTestId('role-name'), { target: { value: 'Too much' } });
    fireEvent.click(screen.getByTestId('save-role'));
    expect(
      await screen.findByText('You cannot give access you do not have yourself.'),
    ).toBeDefined();
  });
});

describe('Admin › Users access drawer', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/users');
    globalThis.IntersectionObserver = class {
      observe(): void {
        // not needed here
      }
      disconnect(): void {
        // not needed here
      }
    } as unknown as typeof IntersectionObserver;
  });
  afterEach(() => {
    restore();
  });

  it('assigns a role from the user drawer', async () => {
    const target = fakeUser({
      id: 'u-9',
      display_name: 'Bilal Requester',
      email: 'bilal@demo.test',
      user_type: 'requester',
    });
    const fake = adminRoutes({
      routes: {
        'GET /api/v1/users': { body: { items: [target], has_more: false, next_cursor: null } },
        'GET /api/v1/users/u-9/access': {
          body: { user_id: 'u-9', role_ids: [], site_ids: [], group_ids: [] },
        },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'PUT /api/v1/users/u-9/roles/r-hr': { status: 204 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Requester'));
    const drawer = await screen.findByTestId('user-access');
    fireEvent.click(await within(drawer).findByLabelText('HR desk'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/users/u-9/roles/r-hr')).toHaveLength(1);
    });
  });
});

describe('menus follow permissions', () => {
  afterEach(() => {
    restore();
  });

  it('a requester sees only the sections their role allows, and no Admin', async () => {
    api({ me: fakeSession({ roles: ['requester'], user_type: 'requester' }) });
    window.history.pushState({}, '', '/');
    render(<App />);
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' });
    await waitFor(() => {
      expect(
        within(nav)
          .getAllByRole('menuitem')
          .map((item) => item.textContent),
      ).toEqual(['Home', 'Requests', 'Knowledge']);
    });
  });

  it('a custom grant adds exactly its section', async () => {
    const me = fakeSession({ roles: ['requester', 'custom_x'], user_type: 'requester' });
    me.permissions = [
      ...(me.permissions ?? []),
      { key: 'reports.view', scope: 'all', scopes: ['all'], conditional: false },
    ];
    api({ me });
    window.history.pushState({}, '', '/');
    render(<App />);
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' });
    await waitFor(() => {
      expect(
        within(nav)
          .getAllByRole('menuitem')
          .map((item) => item.textContent),
      ).toEqual(['Home', 'Requests', 'Knowledge', 'Reports']);
    });
  });
});
