import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { AssetProductType, AssetRecord, AssetState, Vendor } from '@supportx/api-client';

import { App } from '../../App';
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
    fireEvent.click(await screen.findByTestId('asset-dispose-open'));
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
  });
});
