import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import type { CustomField } from '@supportx/api-client';
import { fakeCustomField, fakePermissions, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// A CI type's Fields page (0175 part 2): CustomFieldsTab under a `scope`, with lane A's §11
// conditions: inherited rows read-only with "From <type>", Add sends the scope, reorder moves only
// the type's own fields, nothing incident-specific shows, and retired fields show only when the
// type's own.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const HARDWARE = 'a0000000-0000-7000-8000-0000000000a1';
const SERVER = 'a0000000-0000-7000-8000-0000000000a2';
const type = (id: string, apiName: string, parent: string | null, en: string) => ({
  id,
  parent_id: parent,
  api_name: apiName,
  built_in: false,
  names: { en },
  icon: null,
  ci_count: 0,
  child_count: 0,
  version: 1,
});
const TYPES = [
  type(HARDWARE, 'rack_hardware', null, 'Rack hardware'),
  type(SERVER, 'blade_server', HARDWARE, 'Blade server'),
];

const field = (key: string, overrides: Partial<CustomField>): CustomField =>
  fakeCustomField({ id: `cf-${key}`, key, entity: 'ci', labels: { en: key }, ...overrides });
// Every CI field, in the entity's one order: another type's field sits between ours.
const EVERY = field('every_type', { scope_type_id: null, inherited: true, sort_order: 0 });
const PARENT = field('from_parent', { scope_type_id: HARDWARE, inherited: true, sort_order: 1 });
const OWN_A = field('own_a', { scope_type_id: SERVER, sort_order: 2 });
const ELSEWHERE = field('elsewhere', { scope_type_id: 'other-type', sort_order: 3 });
const OWN_B = field('own_b', { scope_type_id: SERVER, sort_order: 4 });
const PARENT_RETIRED = field('parent_retired', {
  scope_type_id: HARDWARE,
  inherited: true,
  retired: true,
  sort_order: 5,
});
const OWN_RETIRED = field('own_retired', { scope_type_id: SERVER, retired: true, sort_order: 6 });
const FOR_TYPE = [EVERY, PARENT, OWN_A, OWN_B, PARENT_RETIRED, OWN_RETIRED];
const ALL = [EVERY, PARENT, OWN_A, ELSEWHERE, OWN_B, PARENT_RETIRED, OWN_RETIRED];

const ADMIN = fakeSession(
  { roles: ['tenant_admin'] },
  {
    permissions: [
      ...fakePermissions('tenant_admin'),
      { key: 'cmdb.configure', scope: 'all', scopes: ['all'], conditional: false },
    ],
  },
);

function api(extra: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/cmdb/ci-types': { body: { items: TYPES } },
      // One type's fields when asked with `type_id`, every CI field otherwise.
      'GET /api/v1/custom-fields': (call) => ({
        body: call.url.searchParams.get('type_id') === SERVER ? FOR_TYPE : ALL,
      }),
      ...(extra as Record<string, never>),
    },
  });
  restore = fake.restore;
  return fake;
}

function open() {
  window.history.pushState({}, '', `/admin/cmdb/types/${SERVER}/fields`);
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>,
  );
}

describe('Admin › CMDB › a type’s fields', () => {
  it('asks for the type’s fields and shows inherited ones read-only, saying where from', async () => {
    const fake = api();
    open();
    expect(await screen.findByTestId('cf-name-own_a')).toBeDefined();
    const scoped = fake
      .find('GET', '/api/v1/custom-fields')
      .some((c) => c.url.searchParams.get('type_id') === SERVER);
    expect(scoped).toBe(true);
    // From a parent: a link to that type's own fields page, the name isolated for RTL.
    const link = screen.getByTestId('cf-inherited-link-from_parent');
    expect(link.getAttribute('href')).toBe(`/admin/cmdb/types/${HARDWARE}/fields`);
    expect(link.querySelector('bdi')?.textContent).toBe('Rack hardware');
    expect(screen.getByTestId('cf-inherited-every_type').textContent).toBe('From all CI types');
    // Inherited: no actions; own: the usual ones.
    expect(screen.getByTestId('cf-read-only-from_parent')).toBeDefined();
    expect(screen.queryByTestId('cf-edit-from_parent')).toBeNull();
    expect(screen.queryByTestId('cf-remove-every_type')).toBeNull();
    expect(screen.getByTestId('cf-edit-own_a')).toBeDefined();
  });

  it('shows a retired field only when it is the type’s own (condition 5)', async () => {
    api();
    open();
    expect(await screen.findByTestId('cf-name-own_retired')).toBeDefined();
    expect(screen.queryByTestId('cf-name-parent_retired')).toBeNull();
  });

  it('hides everything about incidents: index, sealing, incident wording (condition 2)', async () => {
    api();
    open();
    const card = await screen.findByTestId('settings-custom-fields');
    await within(card).findByTestId('cf-name-own_a');
    expect(within(card).queryByText('Faster filtering')).toBeNull();
    expect(screen.queryByTestId('cf-index-own_a')).toBeNull();
    expect(screen.queryByTestId('cf-seal-own_a')).toBeNull();
    expect(card.textContent).not.toMatch(/incident/i);
    expect(card.textContent).not.toMatch(/template/i);
  });

  it('adds a field to this type: the create sends the scope', async () => {
    const fake = api({
      'POST /api/v1/custom-fields': {
        status: 201,
        body: field('new_one', { scope_type_id: SERVER }),
      },
    });
    open();
    fireEvent.click(await screen.findByTestId('cf-new'));
    fireEvent.change(await screen.findByTestId('cf-label-en'), { target: { value: 'Blade slot' } });
    fireEvent.click(screen.getByTestId('cf-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/custom-fields')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/custom-fields')[0]?.body).toMatchObject({
      entity: 'ci',
      scope_type_id: SERVER,
      labels: { en: 'Blade slot' },
    });
  });

  it('moves only the type’s own fields; every other keeps its place in the one order', async () => {
    const fake = api({ 'PUT /api/v1/custom-fields/order': { body: ALL } });
    open();
    // own_b up: it swaps with own_a, the type's own field above it (not with "elsewhere").
    fireEvent.click(await screen.findByTestId('cf-up-own_b'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/custom-fields/order')).toHaveLength(1);
    });
    expect(fake.find('PUT', '/api/v1/custom-fields/order')[0]?.body).toEqual({
      entity: 'ci',
      ids: [EVERY, PARENT, OWN_B, ELSEWHERE, OWN_A, PARENT_RETIRED, OWN_RETIRED].map((f) => f.id),
    });
    // The first own field cannot move up: nothing above it is the type's own.
    expect(screen.getByTestId('cf-up-own_a').hasAttribute('disabled')).toBe(true);
  });
});
