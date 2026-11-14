import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type {
  FieldAccessRule,
  FieldCatalogue,
  PermissionInfo,
  RoleDetail,
  RoleSummary,
} from '@supportx/api-client';

import { App } from '../../App';
import { fakeEntitlements } from '@supportx/api-client/testing';

import { consoleApi, fakeSession } from '../../test/api';

// ADR-047 slice c: the role editor's Field access tab (lane C's review conditions).

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
const CATALOGUE: FieldCatalogue[] = [
  {
    record_type: 'incident',
    fields: [
      {
        key: 'impact_details',
        label_key: 'work_item.field.impact_details',
        labels: {},
        custom: false,
        personal_data: false,
        sensitive: false,
      },
      {
        key: 'custom.salary_band',
        label_key: null,
        labels: { en: 'Salary band' },
        custom: true,
        personal_data: true,
        sensitive: false,
      },
    ],
  },
];
const RULE: FieldAccessRule = {
  id: 'rule-1',
  role_id: 'r-tech',
  record_type: 'incident',
  field: 'custom.salary_band',
  mode: 'hidden',
  updated_at: '2026-11-14T08:00:00Z',
  updated_by: null,
  version: 3,
};

const PLAN = fakeEntitlements();
const LICENSED = fakeEntitlements({ features: [...PLAN.features, 'field_access'] });

function routes(extra: Record<string, unknown> = {}, licensed = true) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/entitlements': { body: licensed ? LICENSED : PLAN },
      'GET /api/v1/permissions': { body: PERMISSIONS },
      'GET /api/v1/roles': { body: [TECH] },
      'GET /api/v1/roles/r-tech': { body: DETAIL, headers: { ETag: '"1"' } },
      'GET /api/v1/field-access/catalogue': { body: CATALOGUE },
      'GET /api/v1/field-access/rules': { body: [RULE] },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

async function openTab() {
  render(<App />);
  fireEvent.click(await screen.findByTestId('role-row-technician'));
  fireEvent.click(await screen.findByRole('tab', { name: 'Field access' }));
  return screen.findByTestId('field-access-table');
}

describe('Admin › Roles › Field access', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/roles');
  });
  afterEach(() => {
    restore();
  });

  it('lists the fields by name with the role mode; it saves per row, no Save', async () => {
    routes();
    const table = await openTab();
    expect(within(table).getByText('Impact details')).toBeDefined();
    expect(within(table).getByText('Salary band')).toBeDefined();
    expect(within(table).queryByText('custom.salary_band')).toBeNull(); // never the key
    expect(screen.getByTestId('field-access-help').textContent).toBe(
      'Changes on this tab save at once.',
    );
    const tab = screen.getByTestId('field-access-table').closest('.ant-tabs-tabpane');
    expect(tab?.querySelector('[data-testid="save-role"]')).toBeNull();
    expect(within(table).getAllByText('Hidden')).toHaveLength(1);
    expect(within(table).getAllByText('No rule')).toHaveLength(1);
  });

  it('a new mode is a POST with an Idempotency-Key; no rule is a DELETE with If-Match', async () => {
    const fake = routes({
      'POST /api/v1/field-access/rules': { status: 201, body: { ...RULE, id: 'rule-2' } },
      'DELETE /api/v1/field-access/rules/rule-1': { status: 204 },
    });
    await openTab();
    fireEvent.mouseDown(
      within(screen.getByTestId('field-access-mode-impact_details')).getByRole('combobox'),
    );
    fireEvent.click(
      await screen.findByText('Masked', { selector: '.ant-select-item-option-content' }),
    );
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/field-access/rules')).toHaveLength(1);
    });
    const posted = fake.find('POST', '/api/v1/field-access/rules')[0];
    expect(posted?.body).toEqual({
      role_id: 'r-tech',
      record_type: 'incident',
      field: 'impact_details',
      mode: 'masked',
    });
    expect(posted?.headers.get('Idempotency-Key')).toBeTruthy();

    fireEvent.mouseDown(
      within(screen.getByTestId('field-access-mode-custom.salary_band')).getByRole('combobox'),
    );
    const noRule = await screen.findAllByText('No rule', {
      selector: '.ant-select-item-option-content',
    });
    const last = noRule.at(-1);
    if (last === undefined) throw new Error('no "No rule" option');
    fireEvent.click(last);
    await waitFor(() => {
      expect(fake.find('DELETE', '/api/v1/field-access/rules/rule-1')).toHaveLength(1);
    });
    expect(
      fake.find('DELETE', '/api/v1/field-access/rules/rule-1')[0]?.headers.get('If-Match'),
    ).toBe('"3"');
  });

  it('who sees a field opens in a modal, grouped by mode, names isolated', async () => {
    routes({
      'GET /api/v1/field-access/effective': {
        body: {
          record_type: 'incident',
          field: 'custom.salary_band',
          counts: { clear: 1, read_only: 0, masked: 0, hidden: 4 },
          people: {
            clear: [{ id: 'u-1', name: 'Amal Admin' }],
            hidden: [{ id: 'u-2', name: 'Bilal Tech' }],
          },
        },
      },
    });
    await openTab();
    fireEvent.click(screen.getByTestId('field-access-who-custom.salary_band'));
    // The role drawer is a dialog too: the modal is the one with this title.
    const title = await screen.findByText('Who sees Salary band');
    const dialog = title.closest<HTMLElement>('.ant-modal');
    if (dialog === null) throw new Error('the modal is not open');
    expect(
      (await within(dialog).findByTestId('field-access-effective-hidden')).textContent,
    ).toContain('Not shown (4)');
    expect(within(dialog).getByTestId('field-access-effective-hidden').textContent).toContain(
      '3 more',
    );
    expect(within(dialog).getByTestId('field-access-effective-masked').textContent).toContain(
      'Nobody',
    );
  });

  it('a lapsed plan keeps the rules: only "No rule" can be chosen, and the page says why', async () => {
    routes({}, false);
    await openTab();
    expect(await screen.findByText(/no longer includes field access by role/)).toBeDefined();
    // A field with no rule cannot gain one; the hidden one may still be removed.
    const empty = within(screen.getByTestId('field-access-mode-impact_details'));
    expect(empty.getByRole('combobox').hasAttribute('disabled')).toBe(true);
    const held = within(screen.getByTestId('field-access-mode-custom.salary_band'));
    expect(held.getByRole('combobox').hasAttribute('disabled')).toBe(false);
  });
});
