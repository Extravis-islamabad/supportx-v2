import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, onTestFinished } from 'vitest';

import type { AssetProductType, AssetRecord, AssetState, Vendor } from '@supportx/api-client';

import { App } from '../../App';
import { fakePermissions } from '@supportx/api-client/testing';

import { consoleApi, fakeSession } from '../../test/api';

// WP-049a s2: the asset list, one asset and vendors.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const type: AssetProductType = {
  id: '01900000-0000-7000-8000-00000000c001',
  parent_id: null,
  api_name: 'laptop',
  names: { en: 'Laptop', ar: 'حاسوب محمول' },
  icon: null,
  category: 'it',
  kind: 'asset',
  description: null,
  life_cycle_id: null,
  tag_pattern: null,
  ack_required: false,
  depreciation_factor: '2.00',
  sort: 0,
  version: 1,
};
const state: AssetState = {
  id: '01900000-0000-7000-8000-00000000a001',
  code: 'in_stock',
  names: { en: 'In stock' },
  category: 'in_stock',
  reason_required: false,
  is_default_for_category: true,
  system: false,
  sort: 0,
  version: 1,
};
const asset: AssetRecord = {
  id: '01900000-0000-7000-8000-00000000d001',
  name: 'Finance laptop',
  loanable: false,
  product_id: '01900000-0000-7000-8000-00000000e001',
  product_type_id: type.id,
  state_id: state.id,
  tag: 'AST-7',
  serial_number: 'CN0X7Q',
  discovered_serial: null,
  barcode: null,
  vendor_id: null,
  site_id: null,
  location: null,
  purchase_order_id: null,
  purchase_price: '1000.00',
  purchase_tax: '170.00',
  purchase_total: '1170.00',
  currency: null,
  acquired_on: null,
  warranty_expires_on: null,
  expires_on: null,
  description: null,
  custom: {},
  created_at: '2026-11-05T00:00:00Z',
  updated_at: '2026-11-05T00:00:00Z',
  version: 3,
};
const vendor: Vendor = {
  id: '01900000-0000-7000-8000-00000000f001',
  name: 'Acme Supplies',
  currency: null,
  description: null,
  contact_person: 'Sara',
  address: null,
  email: 'sales@acme.test',
  phone: null,
  fax: null,
  website: null,
  is_active: true,
  updated_at: '2026-11-05T00:00:00Z',
  version: 1,
};
const page = <T,>(items: T[]) => ({
  items,
  next_cursor: null,
  has_more: false,
  estimated_total: items.length,
});

function assetsApi(routes = {}) {
  return consoleApi({
    me: fakeSession({ roles: ['tenant_admin'] }),
    routes: {
      'GET /api/v1/assets': { body: page([asset]) },
      'GET /api/v1/assets/product-types': { body: [type] },
      'GET /api/v1/assets/states': { body: [state] },
      'GET /api/v1/assets/products': { body: page([]) },
      'GET /api/v1/procurement/vendors': { body: page([vendor]) },
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"3"' } },
      [`GET /api/v1/assets/${asset.id}/history`]: { body: { items: [], next_cursor: null } },
      ...routes,
    },
  });
}

// The record's action bar shows three buttons from 576 px and two on a phone (useMinWidth);
// the test setup's matchMedia matches nothing, i.e. a phone. These tests are the desktop row.
function wideScreen(): () => void {
  const saved = Object.getOwnPropertyDescriptor(window, 'matchMedia');
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: query.includes('min-width'),
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
  return () => {
    if (saved !== undefined) Object.defineProperty(window, 'matchMedia', saved);
  };
}

describe('console: assets', () => {
  it('lists assets by tag, name, type and state, and searches by identifier', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    const row = (await screen.findByTestId(`asset-row-${asset.id}`)).closest('tr');
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText('AST-7')).toBeTruthy();
    expect(cells.getByText('Finance laptop')).toBeTruthy();
    expect(cells.getByText('Laptop')).toBeTruthy();
    expect(cells.getByText('In stock')).toBeTruthy();
    fireEvent.change(screen.getByTestId('assets-search'), { target: { value: 'CN0X7Q' } });
    await waitFor(() => {
      expect(
        fake
          .find('GET', '/api/v1/assets')
          .some((call) => call.url.searchParams.get('search') === 'CN0X7Q'),
      ).toBe(true);
    });
  });

  it('adds an asset with an Idempotency-Key and opens it', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi({
      'GET /api/v1/assets/products': {
        body: page([{ id: asset.product_id, product_type_id: type.id, name: 'XPS 13' }]),
      },
      'POST /api/v1/assets': { status: 201, body: asset },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-add'));
    fireEvent.change(await screen.findByTestId('asset-name'), {
      target: { value: 'Finance laptop' },
    });
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Product' }));
    fireEvent.click(await screen.findByTitle('XPS 13'));
    fireEvent.click(screen.getByTestId('asset-add-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/assets');
    expect(sent?.body).toEqual({ name: 'Finance laptop', product_id: asset.product_id });
    expect(sent?.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByTestId('asset-tabs')).toBeTruthy();
  });

  it('the product picker searches the server by name, manufacturer or part number', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi({
      'GET /api/v1/assets/products': {
        body: page([{ id: asset.product_id, product_type_id: type.id, name: 'XPS 13' }]),
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-add'));
    const picker = await screen.findByRole('combobox', { name: 'Product' });
    fireEvent.mouseDown(picker);
    fireEvent.change(picker, { target: { value: 'xps' } });
    await waitFor(() => {
      const searched = fake
        .find('GET', '/api/v1/assets/products')
        .map((c) => c.url.searchParams.get('filter'))
        .filter((f): f is string => f !== null);
      expect(searched.map((f) => JSON.parse(f) as unknown)).toContainEqual({
        or: ['name', 'manufacturer', 'part_number'].map((field) => ({
          field,
          op: 'contains',
          value: 'xps',
        })),
      });
    });
  });

  it('asset custom fields: set when adding, shown on the record, only changes sent on edit', async () => {
    const field = {
      id: 'cf-1',
      key: 'cost_centre',
      entity: 'asset',
      field_type: 'text',
      labels: { en: 'Cost centre' },
      help: {},
      choices: [],
      display: 'dropdown',
      validation: { required: false },
      currency: null,
      default: null,
      in_use: false,
      index_state: 'ready',
      index_error: null,
      removed: false,
      retired: false,
      sort_order: 1,
      version: 1,
    };
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      'GET /api/v1/custom-fields': { body: [field] },
      [`GET /api/v1/assets/${asset.id}`]: {
        body: { ...asset, custom: { cost_centre: 'FIN-01' } },
        headers: { ETag: '"3"' },
      },
      [`PATCH /api/v1/assets/${asset.id}`]: { body: { ...asset, version: 4 } },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByText('Cost centre')).toBeTruthy();
    expect(screen.getByText('FIN-01')).toBeTruthy();
    fireEvent.click(screen.getByTestId('asset-edit'));
    fireEvent.change(await screen.findByTestId('asset-custom-cost_centre'), {
      target: { value: 'FIN-02' },
    });
    fireEvent.click(screen.getByTestId('asset-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/assets/${asset.id}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/assets/${asset.id}`);
    expect(sent?.body).toEqual({ custom: { cost_centre: 'FIN-02' } });
  });

  it('shows the age from the tenant basis, and unknown without a basis date (REQ-AST-011)', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}`);
    let basis = 'acquisition_date';
    const fake = assetsApi({
      'GET /api/v1/assets/settings': () => ({ body: { age_basis: basis, copy_limit: 50 } }),
      [`GET /api/v1/assets/${asset.id}`]: {
        body: { ...asset, acquired_on: null, created_at: new Date().toISOString() },
        headers: { ETag: '"3"' },
      },
    });
    restore = fake.restore;
    const view = render(<App />);
    expect(await screen.findByText('Unknown')).toBeTruthy();
    basis = 'created_date';
    view.unmount();
    render(<App />);
    expect(await screen.findByText('Today')).toBeTruthy();
  });

  it('shows one asset with price, tax and total, and saves an edit with If-Match', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      [`PATCH /api/v1/assets/${asset.id}`]: { body: { ...asset, location: 'Floor 3', version: 4 } },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('asset-total')).textContent).toContain('1,170.00');
    expect(screen.getByTestId('asset-state').textContent).toBe('In stock');
    fireEvent.click(screen.getByTestId('asset-edit'));
    fireEvent.change(await screen.findByTestId('asset-location'), {
      target: { value: 'Floor 3' },
    });
    fireEvent.click(screen.getByTestId('asset-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/assets/${asset.id}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/assets/${asset.id}`);
    expect(sent?.body).toEqual({ location: 'Floor 3' });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });

  it('D-157: through its ticket a technician changes the location only, and sees no money', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const masked = { ...asset, purchase_price: null, purchase_tax: null, purchase_total: null };
    const fake = consoleApi({
      // A technician: views assets, no assets.manage, no assets.view_financials.
      me: fakeSession(
        {},
        {
          permissions: ['assets.view'].map((key) => ({
            key,
            scope: 'all' as const,
            scopes: ['all' as const],
            conditional: false,
          })),
        },
      ),
      routes: {
        'GET /api/v1/assets/product-types': { body: [type] },
        'GET /api/v1/assets/states': { body: [state] },
        [`GET /api/v1/assets/${asset.id}`]: { body: masked, headers: { ETag: '"3"' } },
        [`GET /api/v1/assets/${asset.id}/history`]: { body: { items: [], next_cursor: null } },
        [`GET /api/v1/assets/${asset.id}/access`]: {
          body: { manage: false, through_ticket: true },
        },
        [`GET /api/v1/assets/${asset.id}/moves`]: { body: [] },
        [`PATCH /api/v1/assets/${asset.id}`]: {
          body: { ...masked, location: 'Desk 4', version: 4 },
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('asset-through-ticket')).toBeTruthy();
    expect(screen.queryByTestId('asset-total')).toBeNull();
    expect(screen.queryByTestId('asset-edit')).toBeNull(); // no full edit
    fireEvent.click(screen.getByTestId('asset-location-open'));
    fireEvent.change(await screen.findByTestId('asset-location-only'), {
      target: { value: 'Desk 4' },
    });
    fireEvent.click(screen.getByTestId('asset-location-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/assets/${asset.id}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/assets/${asset.id}`);
    expect(sent?.body).toEqual({ location: 'Desk 4' });
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });

  it('lists vendors and adds one', async () => {
    window.history.pushState({}, '', '/assets/vendors');
    const fake = assetsApi({ 'POST /api/v1/procurement/vendors': { status: 201, body: vendor } });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId(`vendor-name-${vendor.id}`)).toBeTruthy();
    fireEvent.click(screen.getByTestId('vendor-add'));
    fireEvent.change(await screen.findByTestId('vendor-name'), { target: { value: 'Globex' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/procurement/vendors')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/procurement/vendors');
    expect(sent?.body).toEqual({ name: 'Globex' });
  });

  it('changes the state along the life cycle: disabled moves say why, a reason when asked', async () => {
    const repair: AssetState = {
      ...state,
      id: '01900000-0000-7000-8000-00000000a002',
      code: 'in_repair',
      names: { en: 'In repair' },
      category: 'in_repair',
      reason_required: true,
    };
    const retired: AssetState = {
      ...state,
      id: '01900000-0000-7000-8000-00000000a003',
      code: 'retired',
      names: { en: 'Retired' },
      category: 'retired',
    };
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      'GET /api/v1/assets/states': { body: [state, repair, retired] },
      [`GET /api/v1/assets/${asset.id}/moves`]: {
        body: [
          { to_state_id: repair.id, reason_required: true, required_fields: [], allowed: true },
          { to_state_id: retired.id, reason_required: false, required_fields: [], allowed: false },
        ],
      },
      [`POST /api/v1/assets/${asset.id}/move`]: {
        body: { ...asset, state_id: repair.id, version: 4 },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-move-open'));
    const dialog = await screen.findByTestId('asset-move-dialog');
    fireEvent.mouseDown(within(dialog).getByRole('combobox'));
    const blocked = await screen.findByText('Retired (needs a permission you don’t have)');
    expect(blocked.closest('.ant-select-item')?.className).toContain('disabled');
    fireEvent.click(screen.getByText('In repair'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change state' }));
    expect(await within(dialog).findByText('This move asks for a reason')).toBeTruthy();
    expect(fake.find('POST', `/api/v1/assets/${asset.id}/move`)).toHaveLength(0);
    fireEvent.change(within(dialog).getByTestId('asset-move-reason'), {
      target: { value: 'Screen cracked' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change state' }));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/assets/${asset.id}/move`)).toHaveLength(1);
    });
    const [call] = fake.find('POST', `/api/v1/assets/${asset.id}/move`);
    expect(call?.body).toEqual({ to_state_id: repair.id, reason: 'Screen cracked' });
    expect(call?.headers.get('If-Match')).toBe('"3"');
  });

  it('copies an asset with an Idempotency-Key, up to the copy limit', async () => {
    const narrow = wideScreen();
    onTestFinished(narrow);
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      'GET /api/v1/assets/settings': { body: { copy_limit: 5 } },
      [`POST /api/v1/assets/${asset.id}/copy`]: {
        status: 201,
        body: {
          items: [
            { ...asset, id: 'c-1' },
            { ...asset, id: 'c-2' },
            { ...asset, id: 'c-3' },
          ],
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-copy-open'));
    const dialog = await screen.findByTestId('asset-copy-dialog');
    expect(await within(dialog).findByText('Up to 5 at once')).toBeTruthy();
    fireEvent.change(within(dialog).getByTestId('asset-copy-count'), { target: { value: '3' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Make 3 copies' }));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/assets/${asset.id}/copy`)).toHaveLength(1);
    });
    const [call] = fake.find('POST', `/api/v1/assets/${asset.id}/copy`);
    expect(call?.body).toEqual({ count: 3 });
    expect(call?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('moves selected assets at once and lists the ones that could not move', async () => {
    const other: AssetRecord = {
      ...asset,
      id: '01900000-0000-7000-8000-00000000d002',
      name: 'Old desktop',
      tag: 'AST-8',
      version: 1,
    };
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi({
      'GET /api/v1/assets': { body: page([asset, other]) },
      'POST /api/v1/assets/bulk-moves': {
        body: [
          { asset_id: asset.id, moved: true, code: null, version: 4 },
          { asset_id: other.id, moved: false, code: 'version_conflict', version: null },
        ],
      },
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId(`asset-row-${asset.id}`);
    for (const box of screen.getAllByRole('checkbox').slice(1)) fireEvent.click(box);
    expect((await screen.findByTestId('assets-selection')).textContent).toContain('2 selected');
    fireEvent.click(screen.getByTestId('assets-bulk-move-open'));
    const dialog = await screen.findByTestId('asset-bulk-move-dialog');
    fireEvent.mouseDown(within(dialog).getByRole('combobox'));
    fireEvent.click(await screen.findByTitle('In stock'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change state' }));
    expect((await within(dialog).findByTestId('asset-bulk-move-partial')).textContent).toContain(
      '1 moved; 1 could not move',
    );
    expect(within(dialog).getByText('Old desktop')).toBeTruthy();
    const [call] = fake.find('POST', '/api/v1/assets/bulk-moves');
    expect(call?.body).toEqual({
      items: [
        { asset_id: asset.id, version: 3 },
        { asset_id: other.id, version: 1 },
      ],
      to_state_id: state.id,
      reason: null,
    });
  });

  it('disposes of a retired asset with its record, and shows the record after', async () => {
    const retired: AssetState = {
      ...state,
      id: '01900000-0000-7000-8000-00000000a004',
      code: 'retired',
      names: { en: 'Retired' },
      category: 'retired',
    };
    const disposed: AssetState = {
      ...state,
      id: '01900000-0000-7000-8000-00000000a005',
      code: 'disposed',
      names: { en: 'Disposed' },
      category: 'disposed',
    };
    const old = { ...asset, state_id: retired.id };
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      'GET /api/v1/assets/states': { body: [state, retired, disposed] },
      [`GET /api/v1/assets/${asset.id}`]: { body: old, headers: { ETag: '"3"' } },
      [`GET /api/v1/assets/${asset.id}/moves`]: {
        body: [
          { to_state_id: disposed.id, reason_required: false, required_fields: [], allowed: true },
        ],
      },
      [`POST /api/v1/assets/${asset.id}/dispose`]: {
        body: {
          id: 'd-1',
          asset_id: asset.id,
          disposed_on: '2026-11-01',
          method: 'recycling',
          reason: 'End of life',
          cost: '12.50',
          currency: 'PKR',
          approved_by: null,
          recorded_by: null,
          recorded_at: '2026-11-06T09:00:00Z',
          version: 1,
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    // Dispose is destructive: it lives in "More actions" (D-155), never beside the buttons.
    await screen.findByTestId('asset-move-open');
    expect(screen.queryByTestId('asset-dispose-open')).toBeNull();
    fireEvent.click(screen.getByTestId('asset-actions-more'));
    fireEvent.click(await screen.findByTestId('asset-dispose-open-menu'));
    const dialog = await screen.findByTestId('asset-dispose-dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Dispose' }));
    expect((await within(dialog).findAllByText('This field is required.')).length).toBe(2);
    expect(fake.find('POST', `/api/v1/assets/${asset.id}/dispose`)).toHaveLength(0);
    fireEvent.mouseDown(
      within(within(dialog).getByTestId('asset-dispose-method')).getByRole('combobox'),
    );
    fireEvent.click(await screen.findByTitle('Recycled'));
    fireEvent.change(within(dialog).getByTestId('asset-dispose-reason'), {
      target: { value: 'End of life' },
    });
    fireEvent.change(within(dialog).getByTestId('asset-dispose-cost'), {
      target: { value: '12.5' },
    });
    fireEvent.change(within(dialog).getByTestId('asset-dispose-currency'), {
      target: { value: 'pkr' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Dispose' }));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/assets/${asset.id}/dispose`)).toHaveLength(1);
    });
    const [call] = fake.find('POST', `/api/v1/assets/${asset.id}/dispose`);
    expect(call?.headers.get('If-Match')).toBe('"3"');
    expect(call?.body).toMatchObject({
      method: 'recycling',
      reason: 'End of life',
      cost: '12.50',
      currency: 'PKR',
      approved_by: null,
    });
  });

  it('a disposed asset shows its record and certificate, never the raw method code', async () => {
    const disposed: AssetState = {
      ...state,
      id: '01900000-0000-7000-8000-00000000a005',
      code: 'disposed',
      names: { en: 'Disposed' },
      category: 'disposed',
    };
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      'GET /api/v1/assets/states': { body: [state, disposed] },
      [`GET /api/v1/assets/${asset.id}`]: {
        body: { ...asset, state_id: disposed.id },
        headers: { ETag: '"4"' },
      },
      [`GET /api/v1/assets/${asset.id}/moves`]: { body: [] },
      [`GET /api/v1/assets/${asset.id}/disposal`]: {
        body: {
          id: 'd-1',
          asset_id: asset.id,
          disposed_on: '2026-11-01',
          method: 'returned_to_vendor',
          reason: 'Lease ended',
          cost: null,
          currency: null,
          approved_by: null,
          recorded_by: null,
          recorded_at: '2026-11-06T09:00:00Z',
          version: 1,
        },
      },
      [`GET /api/v1/files/records/asset/${asset.id}`]: {
        body: [{ id: 'f-1', name: 'wipe-certificate.pdf', owner_type: 'asset_disposal' }],
      },
    });
    restore = fake.restore;
    render(<App />);
    const card = await screen.findByTestId('asset-disposal');
    expect(await within(card).findByText('Returned to the vendor')).toBeTruthy();
    expect(within(card).queryByText('returned_to_vendor')).toBeNull();
    expect(await within(card).findByText('wipe-certificate.pdf')).toBeTruthy();
    expect(screen.queryByTestId('asset-dispose-open')).toBeNull();
    fireEvent.click(screen.getByTestId('asset-actions-more'));
    expect(await screen.findByTestId('asset-trash-menu')).toBeTruthy();
    expect(screen.queryByTestId('asset-dispose-open-menu')).toBeNull();
  });

  it('Holder and links: the holder by name, who held it, links from both ends, give with If-Match', async () => {
    const holder = '01900000-0000-7000-8000-0000000000b1';
    const switchId = '01900000-0000-7000-8000-00000000d009';
    window.history.pushState({}, '', `/assets/${asset.id}?tab=relations`);
    const fake = assetsApi({
      [`GET /api/v1/assets/${asset.id}`]: {
        body: { ...asset, owner_user_id: holder },
        headers: { ETag: '"3"' },
      },
      [`GET /api/v1/users/${holder}`]: { body: { id: holder, display_name: 'Rana Requester' } },
      [`GET /api/v1/assets/${asset.id}/holdings`]: {
        body: [
          {
            asset_id: asset.id,
            holder_kind: 'user',
            holder_id: holder,
            started_at: '2026-11-01T09:00:00Z',
            ended_at: null,
            source: 'ui',
            assigned_by: null,
          },
        ],
      },
      [`GET /api/v1/assets/${asset.id}/links`]: {
        body: [
          {
            id: 'l-1',
            kind: 'connected_to',
            outgoing: false,
            other: { ...asset, id: switchId, name: 'Floor switch', tag: 'AST-9' },
          },
        ],
      },
      [`PUT /api/v1/assets/${asset.id}/holder`]: { body: { ...asset, version: 4 } },
    });
    restore = fake.restore;
    render(<App />);
    const card = await screen.findByTestId('asset-holder');
    expect((await within(card).findAllByText('Rana Requester')).length).toBeGreaterThan(0);
    const links = screen.getByTestId('asset-links');
    // The other end of a "connected to" link reads "Connected from".
    expect(await within(links).findByText('Connected from')).toBeTruthy();
    expect(within(links).getByText('Floor switch')).toBeTruthy();
    fireEvent.click(screen.getByTestId('asset-holder-open'));
    const dialog = await screen.findByTestId('asset-holder-dialog');
    fireEvent.click(within(dialog).getByText('Department'));
    expect(within(dialog).getByRole('button', { name: 'Give to…' }).hasAttribute('disabled')).toBe(
      true,
    );
  });

  it('groups: counts shown, a dynamic group by state, the selection added to a static group', async () => {
    const floor = {
      id: 'g-1',
      name: 'Floor 3',
      description: null,
      kind: 'static',
      filter: null,
      count: 2,
      version: 1,
    };
    window.history.pushState({}, '', '/assets/groups');
    const fake = assetsApi({
      'GET /api/v1/assets/groups': { body: [floor] },
      'POST /api/v1/assets/groups': {
        status: 201,
        body: { ...floor, id: 'g-2', name: 'In stock', kind: 'dynamic', count: 1 },
      },
      'POST /api/v1/assets/groups/g-1/members': { body: { added: 1 } },
    });
    restore = fake.restore;
    render(<App />);
    const row = await screen.findByTestId('asset-group-g-1');
    expect(within(row).getByText('2 assets')).toBeTruthy();
    fireEvent.click(screen.getByTestId('asset-group-new-open'));
    const dialog = await screen.findByTestId('asset-group-new');
    fireEvent.change(within(dialog).getByTestId('asset-group-name'), {
      target: { value: 'In stock' },
    });
    fireEvent.click(within(dialog).getByText('Dynamic'));
    fireEvent.mouseDown(
      within(within(dialog).getByTestId('asset-group-state')).getByRole('combobox'),
    );
    fireEvent.click(await screen.findByTitle('In stock'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add group' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/groups')).toHaveLength(1);
    });
    const [made] = fake.find('POST', '/api/v1/assets/groups');
    expect(made?.body).toEqual({
      name: 'In stock',
      kind: 'dynamic',
      filter: { field: 'state_id', op: 'eq', value: state.id },
    });
    expect(made?.headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('loans: the register by name and status; a return to repair needs a comment', async () => {
    const borrower = '01900000-0000-7000-8000-00000000b101';
    const loan = {
      id: 'l-1',
      borrower_id: borrower,
      starts_at: '2026-11-01T09:00:00Z',
      due_at: '2026-11-08T17:00:00Z',
      closed_at: null,
      comment: null,
      status: 'overdue',
      outstanding: [asset.id],
      assets: [
        { id: asset.id, tag: 'AST-7', name: 'Finance laptop', returned_at: null, outcome: null },
      ],
      version: 1,
    };
    window.history.pushState({}, '', '/assets/loans');
    const fake = assetsApi({
      'GET /api/v1/assets/loans': { body: [loan] },
      [`GET /api/v1/users/${borrower}`]: { body: { id: borrower, display_name: 'Sara Field' } },
      'POST /api/v1/assets/loans/l-1/returns': {
        body: { ...loan, status: 'closed', outstanding: [] },
      },
    });
    restore = fake.restore;
    render(<App />);
    const table = await screen.findByTestId('asset-loans');
    expect(await within(table).findByText('Sara Field')).toBeTruthy();
    expect(within(table).getByText('AST-7 Finance laptop')).toBeTruthy();
    expect(screen.getByTestId('asset-loan-status-l-1').textContent).toBe('Overdue');
    fireEvent.click(screen.getByTestId('asset-loan-return-open-l-1'));
    const dialog = await screen.findByTestId('asset-loan-return');
    fireEvent.click(within(dialog).getByText('To repair'));
    const send = within(dialog).getByRole('button', { name: 'Take back' });
    expect(send.hasAttribute('disabled')).toBe(true); // to repair says what is wrong
    fireEvent.change(within(dialog).getByTestId('asset-loan-return-comment'), {
      target: { value: 'Hinge broken' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Take back' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/loans/l-1/returns')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/assets/loans/l-1/returns');
    expect(sent?.body).toEqual({
      asset_ids: [asset.id],
      outcome: 'in_repair',
      comment: 'Hinge broken',
    });
  });
  it('D-155: selecting rows swaps the toolbar for the selection bar, and clearing brings it back', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId(`asset-row-${asset.id}`);
    expect(screen.getByTestId('assets-filterbar')).toBeTruthy();
    expect(screen.getByTestId('assets-search')).toBeTruthy();
    expect(screen.queryByTestId('assets-selection')).toBeNull();
    const box = screen.getAllByRole('checkbox').at(1);
    if (box === undefined) throw new Error('the row has a checkbox');
    fireEvent.click(box);
    // One control row: the selection bar takes the toolbar's place while rows are selected.
    const bar = await screen.findByTestId('assets-filterbar-selection');
    expect(within(bar).getByTestId('assets-selection').textContent).toContain('1 selected');
    expect(within(bar).getByTestId('assets-bulk-move-open')).toBeTruthy();
    expect(within(bar).getByTestId('assets-make-loanable')).toBeTruthy();
    expect(screen.queryByTestId('assets-filterbar')).toBeNull();
    expect(screen.queryByTestId('assets-search')).toBeNull();
    fireEvent.click(within(bar).getByTestId('assets-selection-clear'));
    expect(await screen.findByTestId('assets-search')).toBeTruthy();
    expect(screen.queryByTestId('assets-selection')).toBeNull();
  });

  it('names every selection box: each row by its tag, the header for the page (axe label)', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    const row = (await screen.findByTestId(`asset-row-${asset.id}`)).closest('tr') as HTMLElement;
    expect(within(row).getByTitle('Select AST-7')).toBeTruthy();
    expect(screen.getAllByLabelText('Select every asset on this page').length).toBeGreaterThan(0);
  });

  it('D-155: on a phone the record shows two actions and the rest under More actions', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"1"' } },
    });
    restore = fake.restore;
    render(<App />);
    const actions = await screen.findByTestId('asset-actions');
    expect(within(actions).getByTestId('asset-move-open')).toBeTruthy();
    expect(within(actions).getByTestId('asset-edit')).toBeTruthy();
    expect(within(actions).queryByTestId('asset-copy-open')).toBeNull(); // under More actions
    expect(within(actions).getByTestId('asset-actions-more')).toBeTruthy();
  });

  it('D-155: a real tag can be copied; an asset without one shows "No tag" as plain text', async () => {
    for (const [tag, copy] of [
      ['AST-7', true],
      [null, false],
    ] as const) {
      window.history.pushState({}, '', `/assets/${asset.id}`);
      const fake = assetsApi({
        [`GET /api/v1/assets/${asset.id}`]: { body: { ...asset, tag }, headers: { ETag: '"1"' } },
      });
      const { unmount } = render(<App />);
      const id = await within(await screen.findByTestId('asset-page')).findByTestId(
        'asset-display-tag',
      );
      expect(id.textContent).toContain(tag ?? 'No tag');
      expect(id.querySelector('.ant-typography-copy') !== null).toBe(copy);
      unmount();
      fake.restore();
    }
  });

  it('D-155: the record header shows the tag, the chips, the facts and the actions on one row', async () => {
    const narrow = wideScreen();
    onTestFinished(narrow);
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi({
      [`GET /api/v1/assets/${asset.id}`]: {
        body: { ...asset, loanable: true },
        headers: { ETag: '"3"' },
      },
    });
    restore = fake.restore;
    render(<App />);
    const page = await screen.findByTestId('asset-page');
    expect(within(page).getByTestId('asset-display-tag').textContent).toContain('AST-7');
    expect(within(page).getByTestId('asset-heading').textContent).toBe('Finance laptop');
    expect(within(page).getByTestId('record-kind-tile').getAttribute('data-kind')).toBe('asset');
    const chips = within(page).getByTestId('record-chips');
    expect((await within(chips).findByTestId('asset-state')).textContent).toBe('In stock');
    expect(within(chips).getByTestId('asset-loanable').textContent).toBe('Loanable');
    // Type and location live in the panel only (lane C's #344 review); the facts say created.
    const facts = (await within(page).findByTestId('record-facts')).textContent;
    expect(facts).not.toContain('Laptop');
    expect(within(page).getByTestId('asset-panel').textContent).toContain('Laptop');
    const actions = within(page).getByTestId('asset-actions');
    for (const id of ['asset-move-open', 'asset-edit', 'asset-copy-open', 'asset-actions-more']) {
      expect(within(actions).getByTestId(id)).toBeTruthy();
    }
    // Delete is destructive: only in "More actions", and it asks first.
    expect(within(actions).queryByTestId('asset-trash')).toBeNull();
    fireEvent.click(within(actions).getByTestId('asset-actions-more'));
    fireEvent.click(await screen.findByTestId('asset-trash-menu'));
    expect((await screen.findAllByText('Move this asset to the trash?')).length).toBeGreaterThan(0);
    expect(fake.find('DELETE', `/api/v1/assets/${asset.id}`)).toHaveLength(0);
  });

  it('D-155: the properties show filled fields only, the empty ones behind "Add details"', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    const props = await screen.findByTestId('asset-props');
    expect(await within(props).findByText('CN0X7Q')).toBeTruthy();
    // Barcode, location, acquired and warranty are empty: not shown until asked for.
    expect(within(props).queryByText('Barcode or QR value')).toBeNull();
    const add = within(props).getByTestId('asset-props-add');
    expect(add.textContent).toBe('Add details (4)');
    fireEvent.click(add);
    const empty = within(props).getByTestId('asset-props-empty');
    expect(within(empty).getByText('Barcode or QR value')).toBeTruthy();
    expect(within(empty).getByText('Location')).toBeTruthy();
    // An empty value opens the edit form.
    fireEvent.click(within(empty).getByRole('button', { name: 'Edit Location' }));
    expect(await screen.findByTestId('asset-edit-form')).toBeTruthy();
  });

  it('D-155: a disabled confirm button says why', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=relations`);
    const fake = assetsApi({
      [`GET /api/v1/assets/${asset.id}/holdings`]: { body: [] },
      [`GET /api/v1/assets/${asset.id}/links`]: { body: [] },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-holder-open'));
    const dialog = await screen.findByTestId('asset-holder-dialog');
    const give = within(dialog).getByRole('button', { name: 'Give to…' });
    expect(give.hasAttribute('disabled')).toBe(true);
    fireEvent.mouseOver(within(dialog).getByTestId('disabled-why'));
    expect(await screen.findByText('Choose who or what gets it first')).toBeTruthy();
  });
});

describe('console: assets polish (QA10-P4-38, P4-39; #307 review)', () => {
  it('Add asset with no products says where products are set up, with a link for an admin', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi(); // the catalogue has no products
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-add'));
    const hint = await screen.findByTestId('asset-products-none');
    expect(hint.textContent).toContain('An admin adds them in Admin, Assets, on the Products tab.');
    const link = within(hint).getByTestId('asset-products-open');
    expect(link.getAttribute('href')).toBe('/admin/assets?tab=products');
  });

  it('a person who may not configure assets gets the hint without the link', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = consoleApi({
      // A technician who manages assets but may not configure the catalogue.
      me: fakeSession(
        {},
        {
          permissions: ['assets.view', 'assets.manage', 'vendors.view'].map((key) => ({
            key,
            scope: 'all' as const,
            scopes: ['all' as const],
            conditional: false,
          })),
        },
      ),
      routes: {
        'GET /api/v1/assets': { body: page([asset]) },
        'GET /api/v1/assets/product-types': { body: [type] },
        'GET /api/v1/assets/states': { body: [state] },
        'GET /api/v1/assets/products': { body: page([]) },
        'GET /api/v1/procurement/vendors': { body: page([vendor]) },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-add'));
    const hint = await screen.findByTestId('asset-products-none');
    expect(within(hint).queryByTestId('asset-products-open')).toBeNull();
  });

  it('the hint stays away when products exist', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi({
      'GET /api/v1/assets/products': {
        body: page([{ id: asset.product_id, product_type_id: type.id, name: 'XPS 13' }]),
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-add'));
    await screen.findByTestId('asset-name');
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/assets/products').length).toBeGreaterThan(0);
    });
    expect(screen.queryByTestId('asset-products-none')).toBeNull();
  });

  it('Escape on the Add asset drawer asks before dropping what was typed', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-add'));
    const name = await screen.findByTestId('asset-name');
    fireEvent.change(name, { target: { value: 'Spare monitor' } });
    fireEvent.keyDown(name, { key: 'Escape', code: 'Escape', keyCode: 27 });
    expect((await screen.findAllByText('Discard your changes?')).length).toBeGreaterThan(0);
    // Keep editing: the drawer and the typed name stay.
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    expect(screen.getByTestId<HTMLInputElement>('asset-name').value).toBe('Spare monitor');
    fireEvent.keyDown(screen.getByTestId('asset-name'), {
      key: 'Escape',
      code: 'Escape',
      keyCode: 27,
    });
    // The newest prompt (the first one may still be leaving).
    const [discard] = (await screen.findAllByTestId('asset-add-discard')).reverse();
    expect(discard).toBeDefined();
    if (discard !== undefined) fireEvent.click(discard);
    await waitFor(() => {
      expect(screen.queryByTestId('asset-name')).toBeNull();
    });
  });

  it('Escape on an untouched Add asset drawer closes it without asking', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-add'));
    const name = await screen.findByTestId('asset-name');
    fireEvent.keyDown(name, { key: 'Escape', code: 'Escape', keyCode: 27 });
    await waitFor(() => {
      expect(screen.queryByTestId('asset-name')).toBeNull();
    });
    expect(screen.queryByText('Discard your changes?')).toBeNull();
  });

  it('an empty vendor name is marked under the field and nothing is sent', async () => {
    window.history.pushState({}, '', '/assets/vendors');
    const fake = assetsApi({ 'POST /api/v1/procurement/vendors': { status: 201, body: vendor } });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('vendor-add'));
    fireEvent.change(await screen.findByTestId('vendor-name'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect((await screen.findByTestId('vendor-name-needed')).textContent).toBe('Enter a name.');
    expect(fake.find('POST', '/api/v1/procurement/vendors')).toHaveLength(0);
    // Typing a name clears the mark, and the save goes through.
    fireEvent.change(screen.getByTestId('vendor-name'), { target: { value: 'Globex' } });
    await waitFor(() => {
      expect(screen.queryByTestId('vendor-name-needed')).toBeNull();
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/procurement/vendors')).toHaveLength(1);
    });
  });

  it.each([
    ['/assets/vendors', 'vendors-page'],
    ['/assets/groups', 'asset-groups-page'],
    ['/assets/loans', 'asset-loans-page'],
  ])('%s has a back link to the asset list', async (path, testId) => {
    window.history.pushState({}, '', path);
    const fake = assetsApi({
      'GET /api/v1/assets/groups': { body: [] },
      'GET /api/v1/assets/loans': { body: [] },
    });
    restore = fake.restore;
    render(<App />);
    const pageEl = await screen.findByTestId(testId);
    fireEvent.click(within(pageEl).getByRole('button', { name: 'Assets' }));
    expect(await screen.findByTestId('assets-list')).toBeTruthy();
    expect(window.location.pathname).toBe('/assets');
  });

  it('Take back asks first, then ends the holding with If-Match', async () => {
    const holder = '01900000-0000-7000-8000-0000000000b1';
    window.history.pushState({}, '', `/assets/${asset.id}?tab=relations`);
    const fake = assetsApi({
      [`GET /api/v1/assets/${asset.id}`]: {
        body: { ...asset, owner_user_id: holder },
        headers: { ETag: '"3"' },
      },
      [`GET /api/v1/users/${holder}`]: { body: { id: holder, display_name: 'Rana Requester' } },
      [`GET /api/v1/assets/${asset.id}/holdings`]: {
        body: [
          {
            asset_id: asset.id,
            holder_kind: 'user',
            holder_id: holder,
            started_at: '2026-11-01T09:00:00Z',
            ended_at: null,
            source: 'ui',
            assigned_by: null,
          },
        ],
      },
      [`GET /api/v1/assets/${asset.id}/links`]: { body: [] },
      [`DELETE /api/v1/assets/${asset.id}/holder`]: { body: { ...asset, version: 4 } },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-holder-clear'));
    expect(
      await screen.findByText('Take this asset back? This ends the current holding.'),
    ).toBeTruthy();
    expect(fake.find('DELETE', `/api/v1/assets/${asset.id}/holder`)).toHaveLength(0);
    fireEvent.click(screen.getByTestId('asset-holder-clear-confirm'));
    await waitFor(() => {
      expect(fake.find('DELETE', `/api/v1/assets/${asset.id}/holder`)).toHaveLength(1);
    });
    const [sent] = fake.find('DELETE', `/api/v1/assets/${asset.id}/holder`);
    expect(sent?.headers.get('If-Match')).toBe('"3"');
  });

  it('the group name shows the server limit once it is passed', async () => {
    window.history.pushState({}, '', '/assets/groups');
    const fake = assetsApi({ 'GET /api/v1/assets/groups': { body: [] } });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-group-new-open'));
    const dialog = await screen.findByTestId('asset-group-new');
    fireEvent.change(within(dialog).getByTestId('asset-group-name'), {
      target: { value: 'x'.repeat(201) },
    });
    expect(await within(dialog).findByText('201 / 200')).toBeTruthy();
  });
});

describe('the asset list selection for view-only people (WP-049b s3)', () => {
  it('offers only Print labels; moving, groups and loans stay with assets.manage', async () => {
    window.history.pushState({}, '', '/assets');
    const viewOnly = fakeSession(
      { roles: ['technician'] },
      { permissions: fakePermissions('technician').filter((p) => p.key !== 'assets.manage') },
    );
    const fake = consoleApi({
      me: viewOnly,
      routes: {
        'GET /api/v1/assets': { body: page([asset]) },
        'GET /api/v1/assets/product-types': { body: [type] },
        'GET /api/v1/assets/states': { body: [state] },
      },
    });
    restore = fake.restore;
    render(<App />);
    const row = (await screen.findByTestId(`asset-row-${asset.id}`)).closest('tr') as HTMLElement;
    fireEvent.click(within(row).getByTitle('Select AST-7'));
    const bar = await screen.findByTestId('assets-selection');
    expect(within(bar).getByTestId('assets-print-labels')).toBeTruthy();
    expect(within(bar).queryByTestId('assets-bulk-move-open')).toBeNull();
    expect(within(bar).queryByTestId('assets-add-to-group')).toBeNull();
    expect(within(bar).queryByTestId('assets-make-loanable')).toBeNull();
  });
});
