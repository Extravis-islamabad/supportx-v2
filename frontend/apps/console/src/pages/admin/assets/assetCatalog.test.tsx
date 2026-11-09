import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type {
  AssetLifeCycle,
  AssetProductType,
  AssetSettings,
  AssetState,
} from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeEntitlements, fakeSession } from '../../../test/api';
import { codeFrom } from './shared';

// WP-049a s1 (D-141): the asset catalogue's admin page.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const settings: AssetSettings = {
  tag_pattern: 'AST-{n}',
  age_basis: 'acquisition_date',
  cost_includes_tax: true,
  copy_limit: 50,
  site_follows_owner: false,
  portal_own_assets_only: true,
  email_include_assets: false,
  scan_retention_months: 12,
  version: 3,
};
const states: AssetState[] = [
  {
    id: '01900000-0000-7000-8000-00000000a001',
    code: 'in_store',
    names: { en: 'In store', ar: 'في المخزن' },
    category: 'in_stock',
    reason_required: false,
    is_default_for_category: true,
    system: false,
    sort: 0,
    version: 1,
  },
  {
    id: '01900000-0000-7000-8000-00000000a002',
    code: 'disposed',
    names: { en: 'Disposed' },
    category: 'disposed',
    reason_required: true,
    is_default_for_category: true,
    system: true,
    sort: 1,
    version: 1,
  },
];
const lifeCycles: AssetLifeCycle[] = [
  {
    id: '01900000-0000-7000-8000-00000000b001',
    code: 'standard',
    names: { en: 'Standard' },
    is_default: true,
    moves: [],
    version: 1,
  },
];
const types: AssetProductType[] = [
  {
    id: '01900000-0000-7000-8000-00000000c001',
    parent_id: null,
    api_name: 'it_hardware',
    names: { en: 'IT hardware', ar: 'أجهزة تقنية المعلومات' },
    icon: null,
    category: 'it',
    kind: 'asset',
    description: null,
    life_cycle_id: null,
    tag_pattern: null,
    ack_required: false,
    sort: 0,
    version: 1,
  },
  {
    id: '01900000-0000-7000-8000-00000000c002',
    parent_id: '01900000-0000-7000-8000-00000000c001',
    api_name: 'laptop',
    names: { en: 'Laptop' },
    icon: null,
    category: 'it',
    kind: 'asset',
    description: null,
    life_cycle_id: null,
    tag_pattern: null,
    ack_required: true,
    sort: 0,
    version: 2,
  },
];

function catalogueApi(routes = {}, entitlements = fakeEntitlements()) {
  return consoleApi({
    me: fakeSession({ roles: ['tenant_admin'], user_type: 'technician' }),
    routes: {
      'GET /api/v1/entitlements': { body: entitlements },
      'GET /api/v1/assets/settings': { body: settings },
      'GET /api/v1/assets/states': { body: states },
      'GET /api/v1/assets/life-cycles': { body: lifeCycles },
      'GET /api/v1/assets/product-types': { body: types },
      'GET /api/v1/assets/products': {
        body: { items: [], next_cursor: null, has_more: false, estimated_total: 0 },
      },
      ...routes,
    },
  });
}

describe('console: asset catalogue', () => {
  it('shows the product types as a tree, by their stored names, never their codes', async () => {
    window.history.pushState({}, '', '/admin/assets');
    const fake = catalogueApi();
    restore = fake.restore;
    render(<App />);
    const tree = await screen.findByTestId('asset-types');
    expect(within(tree).getByText('IT hardware')).toBeTruthy();
    expect(within(tree).queryByText('it_hardware')).toBeNull();
    expect(within(tree).getAllByText('IT').length).toBeGreaterThan(0);
  });

  it('adds a state with a code made from its English name and an Idempotency-Key', async () => {
    window.history.pushState({}, '', '/admin/assets');
    const fake = catalogueApi({
      'POST /api/v1/assets/states': { status: 201, body: { ...states[0], code: 'with_courier' } },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'States' }));
    fireEvent.click(await screen.findByTestId('asset-state-add'));
    fireEvent.change(await screen.findByTestId('asset-state-name-en'), {
      target: { value: 'With courier' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/states')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/assets/states');
    expect(sent?.body).toMatchObject({
      code: 'with_courier',
      names: { en: 'With courier' },
      category: 'in_stock',
    });
    expect(sent?.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('saves only the settings changed, with If-Match on the version shown', async () => {
    window.history.pushState({}, '', '/admin/assets');
    const fake = catalogueApi({
      'PATCH /api/v1/assets/settings': { body: { ...settings, cost_includes_tax: false } },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Settings' }));
    const save = await screen.findByTestId('asset-settings-save');
    expect(save.closest('button')?.disabled).toBe(true);
    fireEvent.click(screen.getByTestId('asset-cost_includes_tax'));
    fireEvent.click(save);
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/assets/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/assets/settings');
    expect(sent?.body).toEqual({ cost_includes_tax: false });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });

  // While the plan loads the licence context assumes nothing is missing (its rule), so this
  // checks what the page says once the plan is known; the server refuses the calls anyway.
  it('says the catalogue is not in the plan', async () => {
    window.history.pushState({}, '', '/admin/assets');
    const plan = fakeEntitlements();
    const fake = catalogueApi(
      {},
      { ...plan, features: plan.features.filter((feature) => feature !== 'assets') },
    );
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('asset-catalogue-locked')).toBeTruthy();
    expect(screen.queryByTestId('asset-catalogue-tabs')).toBeNull();
  });
});

describe('asset codes', () => {
  it('come from the English name, unique, with a fallback for other scripts', () => {
    expect(codeFrom('With courier', new Set(), 'state')).toBe('with_courier');
    expect(codeFrom('With courier', new Set(['with_courier']), 'state')).toBe('with_courier_2');
    expect(codeFrom('مع المندوب', new Set(), 'state')).toBe('state');
    expect(codeFrom('3D printers', new Set(['type']), 'type')).toBe('type_2');
    expect(codeFrom('Café chairs', new Set(), 'type')).toBe('cafe_chairs');
  });
});
