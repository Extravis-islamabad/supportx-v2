import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { PermissionInfo, RoleDetail, RoleSummary } from '@supportx/api-client';

import { App } from '../../App';
import { consoleApi, fakeSession, fakeUser, problem } from '../../test/api';
import { fakeEntitlements } from '@supportx/api-client/testing';

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

  it('PEO-07: Save is never disabled without a reason; an empty name says so and sends nothing', async () => {
    const fake = adminRoutes({ routes: {} });
    render(<App />);
    fireEvent.click(await screen.findByTestId('new-role'));
    const save = await screen.findByTestId('save-role');
    expect(save.hasAttribute('disabled')).toBe(false);
    fireEvent.click(save);
    expect(await screen.findByText('This field is required.')).toBeDefined();
    expect(document.activeElement?.id).toBe('role-name');
    expect(fake.find('POST', '/api/v1/roles')).toHaveLength(0);
  });

  it('with a read-only licence a custom role cannot be deleted (§17 item 3)', async () => {
    adminRoutes({
      routes: {
        'GET /api/v1/roles/r-hr': { body: { ...HR, permissions: [] }, headers: { ETag: '"4"' } },
        'GET /api/v1/entitlements': {
          body: fakeEntitlements({ state: 'read_only', state_reason: 'expired', writable: false }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('role-row-custom_abc'));
    const remove = await screen.findByTestId('delete-role');
    await waitFor(() => {
      expect(remove.hasAttribute('disabled')).toBe(true);
    });
  });

  it('opens built-in roles read-only', async () => {
    adminRoutes();
    render(<App />);
    fireEvent.click(await screen.findByTestId('role-row-technician'));
    expect(await screen.findByText(/Built-in roles cannot be changed/)).toBeDefined();
    expect(screen.queryByTestId('save-role')).toBeNull();
    // D-153: what it is for and what it reaches, in words; never a Delete, always a copy.
    const about = screen.getByTestId('role-built-in');
    expect(about.textContent).not.toMatch(/role\.|technician\./);
    expect(screen.getByTestId('role-default-scope').textContent).toMatch(/^Reaches: /);
    expect(screen.queryByTestId('delete-role')).toBeNull();
    expect(screen.getByTestId('role-scope-technician').textContent).toMatch(/^Reaches: /);
  });

  it('PEO-06: a built-in role opens on what it grants, scopes as text, with a search', async () => {
    adminRoutes();
    render(<App />);
    fireEvent.click(await screen.findByTestId('role-row-technician'));
    // Granted only by default: requests.view is held, users.view is not, so it is hidden.
    const held = await screen.findByTestId('scope-requests.view');
    expect(held.tagName).not.toBe('INPUT');
    expect(held.textContent).toBe('All records');
    expect(screen.queryByTestId('scope-users.view')).toBeNull();
    fireEvent.click(screen.getByTestId('role-granted-only'));
    expect(await screen.findByTestId('scope-users.view')).toBeTruthy();
    fireEvent.change(screen.getByTestId('role-permission-search'), {
      target: { value: 'zzz-nothing' },
    });
    expect(await screen.findByText('No permission matches')).toBeTruthy();
    expect(screen.getByTestId('copy-role').textContent).toBe('Copy and customise');
  });

  it('REQ-ADM-017: a built-in role is copied into a new custom role with the same grants', async () => {
    const fake = adminRoutes({
      routes: {
        'POST /api/v1/roles': {
          status: 201,
          body: { ...HR, id: 'r-copy', name: 'Copy of Technician' },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('role-row-technician'));
    fireEvent.click(await screen.findByTestId('copy-role'));
    const name = await screen.findByTestId('role-name');
    expect((name as HTMLInputElement).value).toBe('Copy of Technician');
    fireEvent.click(screen.getByTestId('save-role'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/roles')).toHaveLength(1);
    });
    const body = fake.find('POST', '/api/v1/roles')[0]?.body as {
      name: string;
      permissions: { permission: string; scope: string }[];
    };
    expect(body.name).toBe('Copy of Technician');
    expect(body.permissions).toEqual([
      { permission: 'requests.view', scope: 'all', condition: null },
    ]);
  });

  it('REQ-ADM-017: two roles compared side by side, by module, the differences marked', async () => {
    adminRoutes({
      routes: {
        'GET /api/v1/roles/r-hr': {
          body: {
            ...HR,
            permissions: [
              { permission: 'requests.view', scope: 'group', condition: null },
              { permission: 'users.view', scope: 'all', condition: null },
            ],
          },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('compare-roles'));
    const drawer = await screen.findByTestId('role-compare');
    const pick = async (testId: string, label: string) => {
      fireEvent.mouseDown(within(drawer).getByTestId(testId).querySelector('input') ?? drawer);
      // The newest list is the last one in the page (the other select's list stays mounted).
      const found = await screen.findAllByText(label, {
        selector: '.ant-select-item-option-content',
      });
      const last = found.at(-1);
      if (last !== undefined) fireEvent.click(last);
    };
    await pick('role-compare-first', 'Technician');
    await pick('role-compare-second', 'HR desk');
    expect(await screen.findByTestId('role-compare-diff-requests.view')).toBeDefined();
    expect(await screen.findByTestId('role-compare-diff-users.view')).toBeDefined();
    const table = screen.getByTestId('role-compare-table');
    expect(table.textContent).toContain('Not granted');
    expect(table.textContent).not.toMatch(/requests\.view|users\.view/);
  });

  it('REQ-ADM-015 AC2: the groups carrying a role are listed by name; adding one gives it them', async () => {
    const fake = adminRoutes({
      routes: {
        'GET /api/v1/roles/r-hr': {
          body: { ...HR, permissions: [], group_ids: ['g-night'] },
          headers: { ETag: '"4"' },
        },
        'GET /api/v1/organization/groups': {
          body: [
            { id: 'g-night', name: 'Night shift', member_ids: [], disabled: false, version: 1 },
            { id: 'g-day', name: 'Day shift', member_ids: [], disabled: false, version: 1 },
          ],
        },
        'PUT /api/v1/roles/r-hr/groups/g-day': { status: 204 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('role-row-custom_abc'));
    const groups = await screen.findByTestId('role-groups');
    expect(await within(groups).findByText('Night shift')).toBeDefined();
    fireEvent.mouseDown(
      within(groups).getByTestId('role-groups-add').querySelector('input') ?? groups,
    );
    fireEvent.click(
      await screen.findByText('Day shift', { selector: '.ant-select-item-option-content' }),
    );
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/roles/r-hr/groups/g-day')).toHaveLength(1);
    });
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
        'GET /api/v1/users/u-9': { body: target },
        'GET /api/v1/organization/departments': { body: [] },
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
    // People admins open the person drawer (WP-021); roles are on its Access tab.
    fireEvent.click(await screen.findByRole('tab', { name: 'Access' }));
    const drawer = await screen.findByTestId('user-access');
    fireEvent.click(await within(drawer).findByLabelText('HR desk'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/users/u-9/roles/r-hr')).toHaveLength(1);
    });
  });

  it('keeps a contact on one line and lets a keyboard reach the scrolling table', async () => {
    const contact = fakeUser({
      id: 'u-7',
      display_name: 'Ayesha Contact',
      email: 'ayesha@demo.test',
      user_type: 'requester',
      can_sign_in: false,
    });
    adminRoutes({
      routes: {
        'GET /api/v1/users': { body: { items: [contact], has_more: false, next_cursor: null } },
        'GET /api/v1/organization/departments': { body: [] },
        'GET /api/v1/organization/sites': { body: [] },
      },
    });
    render(<App />);
    // QA6 ADM-02: the name and its chip share one line, the chip never squeezing the name.
    const cell = await screen.findByTestId('user-name-u-7');
    expect(cell.className).not.toContain('ant-flex-wrap-wrap');
    const name = within(cell).getByText('Ayesha Contact');
    expect(name.classList.contains('sx-cell-text')).toBe(true);
    expect(name.getAttribute('title')).toBe('Ayesha Contact');
    // The chips keep their own width: the name gives way first.
    const chips = cell.querySelector('span[style*="flex-shrink: 0"]');
    expect(chips?.textContent).toBe('Contact');
    // Visual matrix at 390 px (axe scrollable-region-focusable): the table's own scroll box is a
    // named region a keyboard can focus.
    const region = await screen.findByRole('region', { name: 'People' });
    expect(region.classList.contains('ant-table-content')).toBe(true);
    expect(region.tabIndex).toBe(0);
  });
});

describe('Access drawer: roles held through groups (WP-042)', () => {
  afterEach(() => {
    restore();
  });

  it('names the group a role comes from', async () => {
    window.history.pushState({}, '', '/admin/users');
    const target = fakeUser({ id: 'u-9', display_name: 'Bilal Tech', user_type: 'technician' });
    adminRoutes({
      routes: {
        'GET /api/v1/users': { body: { items: [target], has_more: false, next_cursor: null } },
        'GET /api/v1/users/u-9': { body: target },
        'GET /api/v1/organization/departments': { body: [] },
        'GET /api/v1/users/u-9/access': {
          body: {
            user_id: 'u-9',
            role_ids: [],
            site_ids: [],
            group_ids: ['g-night'],
            group_roles: [{ role_id: 'r-hr', group_id: 'g-night' }],
          },
        },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/organization/groups': {
          body: [
            {
              id: 'g-night',
              name: 'Night shift',
              member_ids: ['u-9'],
              disabled: false,
              version: 1,
            },
          ],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Tech'));
    fireEvent.click(await screen.findByRole('tab', { name: 'Access' }));
    const drawer = await screen.findByTestId('user-access');
    expect((await within(drawer).findByTestId('role-through-custom_abc')).textContent).toBe(
      'through Night shift',
    );
  });
});

describe('menus follow permissions', () => {
  afterEach(() => {
    restore();
  });

  // Requester-only people never reach the console (D-129): menus follow the permissions of a
  // console user, here one with a narrow custom role beside the requester role.
  it('a narrow role sees only the sections it allows, and no Admin', async () => {
    api({ me: fakeSession({ roles: ['requester', 'custom_narrow'], user_type: 'technician' }) });
    window.history.pushState({}, '', '/');
    render(<App />);
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' });
    await waitFor(() => {
      expect(
        within(nav)
          .getAllByRole('menuitem')
          .map((item) => item.textContent),
      ).toEqual(['Home', 'My tasks', 'Service requests', 'Knowledge']);
    });
  });

  it('a custom grant adds exactly its section', async () => {
    const me = fakeSession({ roles: ['requester', 'custom_x'], user_type: 'technician' });
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
        // reports.view opens dashboards too: a dashboard is made of reports (WP-036).
      ).toEqual(['Home', 'My tasks', 'Service requests', 'Knowledge', 'Dashboards', 'Reports']);
    });
  });
});
