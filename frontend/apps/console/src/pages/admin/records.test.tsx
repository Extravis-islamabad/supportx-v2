import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type {
  PermissionInfo,
  ResourceCriteria,
  ResourceRule,
  RoleDetail,
  RoleSummary,
} from '@supportx/api-client';

import { App } from '../../App';
import { fakeEntitlements } from '@supportx/api-client/testing';

import { consoleApi, fakeSession } from '../../test/api';

// ADR-053: the role editor's Records tab (which assets and CIs a role shows, narrow-only).

let restore: () => void = () => undefined;
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const TECH: RoleSummary = {
  id: 'r-tech',
  key: 'technician',
  name: 'technician',
  description: null,
  is_system: true,
  user_count: 3,
  version: 1,
};
const DETAIL: RoleDetail = { ...TECH, permissions: [] };
const PERMISSIONS: PermissionInfo[] = [];
const SITE = 'b0000000-0000-7000-8000-000000000001';
const CRITERIA: ResourceCriteria[] = [
  {
    resource: 'ci',
    criteria: [
      { key: 'type_ids', kind: 'ids', values: [] },
      { key: 'site_ids', kind: 'ids', values: [] },
      { key: 'criticality_max', kind: 'ceiling', values: ['low', 'medium', 'high', 'critical'] },
    ],
  },
  {
    resource: 'asset',
    criteria: [{ key: 'site_ids', kind: 'ids', values: [] }],
  },
];
const RULE: ResourceRule = {
  id: 'rule-1',
  role_id: 'r-tech',
  resource: 'ci',
  criteria: { site_ids: [SITE] },
  updated_at: '2026-11-20T08:00:00Z',
  updated_by: null,
  version: 2,
};

const PLAN = fakeEntitlements();
const LICENSED = fakeEntitlements({ features: [...PLAN.features, 'fine_grained_access'] });

function routes(licensed = true) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/entitlements': { body: licensed ? LICENSED : PLAN },
      'GET /api/v1/permissions': { body: PERMISSIONS },
      'GET /api/v1/roles': { body: [TECH] },
      'GET /api/v1/roles/r-tech': { body: DETAIL, headers: { ETag: '"1"' } },
      'GET /api/v1/field-access/catalogue': { body: [] },
      'GET /api/v1/field-access/rules': { body: [] },
      'GET /api/v1/resource-access/criteria': { body: CRITERIA },
      'GET /api/v1/resource-access/rules': { body: [RULE] },
      'GET /api/v1/organization/sites': { body: [{ id: SITE, name: 'Karachi office' }] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/assets/product-types': { body: [] },
    },
  });
  restore = fake.restore;
  return fake;
}

async function openTab() {
  render(<App />);
  fireEvent.click(await screen.findByTestId('role-row-technician'));
  fireEvent.click(await screen.findByRole('tab', { name: 'Records' }));
  return screen.findByTestId('records-ci');
}

describe('Admin › Roles › Records', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/roles');
  });
  afterEach(() => {
    restore();
  });

  it('lists a role’s rules by name, never an ID', async () => {
    routes();
    const card = await openTab();
    const rule = within(card).getByTestId('records-rule-rule-1');
    expect(rule.textContent).toContain('Karachi office');
    expect(rule.textContent).not.toContain(SITE);
    expect(screen.getByTestId('records-add-ci')).toBeDefined();
    expect(within(screen.getByTestId('records-asset')).getByText(/No rule/)).toBeDefined();
  });

  it('a lapsed plan keeps the rules: they show and can be removed, not added or changed', async () => {
    routes(false);
    await openTab();
    expect(screen.getByTestId('records-unlicensed')).toBeDefined();
    expect(screen.queryByTestId('records-add-ci')).toBeNull();
    expect(screen.getByTestId('records-remove-rule-1')).toBeDefined();
    const rule = screen.getByTestId('records-rule-rule-1');
    expect(within(rule).queryByText('Edit')).toBeNull();
  });
});
