import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { AssetProductType, AssetRecord, AssetState } from '@supportx/api-client';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';
import { raisePath } from './raise';
import { branchCounts, startsWith } from './typeCounts';

// WP-049b s4a: the product type tree (keyboard, counts, a node and its types), built-in and
// saved views with favourites, widths kept per view, the linked records panel, raising a work
// item from an asset.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const typeOf = (id: string, apiName: string, en: string, parent: string | null, sort = 0) =>
  ({
    id,
    parent_id: parent,
    api_name: apiName,
    names: { en },
    icon: null,
    category: 'it',
    kind: 'asset',
    description: null,
    life_cycle_id: null,
    tag_pattern: null,
    ack_required: false,
    sort,
    version: 1,
  }) satisfies AssetProductType;
const COMPUTER = '01900000-0000-7000-8000-0000000c0001';
const STATION = '01900000-0000-7000-8000-0000000c0002';
const LAPTOP = '01900000-0000-7000-8000-0000000c0003';
const PHONE = '01900000-0000-7000-8000-0000000c0004';
const types = [
  typeOf(COMPUTER, 'computer', 'Computer', null, 0),
  typeOf(STATION, 'workstation', 'Workstation', COMPUTER, 0),
  typeOf(LAPTOP, 'laptop', 'Laptop', COMPUTER, 1),
  typeOf(PHONE, 'phone', 'Phone', null, 1),
];
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
  name: 'Station one',
  loanable: false,
  product_id: '01900000-0000-7000-8000-00000000e001',
  product_type_id: STATION,
  state_id: state.id,
  tag: 'AST-1',
  serial_number: 'SN-1',
  discovered_serial: null,
  barcode: null,
  vendor_id: null,
  site_id: null,
  owner_user_id: '01900000-0000-7000-8000-0000000f0001',
  location: null,
  purchase_order_id: null,
  purchase_price: null,
  purchase_tax: null,
  purchase_total: null,
  currency: null,
  acquired_on: null,
  warranty_expires_on: null,
  expires_on: null,
  description: null,
  custom: {},
  created_at: '2026-11-05T00:00:00Z',
  updated_at: '2026-11-05T00:00:00Z',
  version: 1,
};
const listPage = {
  items: [asset],
  next_cursor: null,
  has_more: false,
  estimated_total: 1,
  people: { [asset.owner_user_id ?? '']: 'Aisha Khan' },
  parents: {},
  products: { [asset.product_id]: 'OptiPlex 7010' },
};
const savedView = {
  view_key: 'custom:01900000-0000-7000-8000-0000000b0001',
  saved_view_id: '01900000-0000-7000-8000-0000000b0001',
  name: 'Finance laptops',
  filter: { field: 'name', op: 'contains', value: 'Finance' },
  columns: [],
  sort: null,
  page_size: 50,
  favourite: true,
  version: 2,
  updated_at: '2026-11-11T00:00:00Z',
};
const noSetting = (key: string) => ({
  view_key: key,
  columns: [],
  sort: null,
  page_size: 50,
  favourite: false,
  version: null,
});

function viewsApi(routes = {}) {
  return consoleApi({
    me: fakeSession({ roles: ['tenant_admin'] }),
    routes: {
      'GET /api/v1/assets': { body: listPage },
      'GET /api/v1/assets/product-types': { body: types },
      'GET /api/v1/assets/states': { body: [state] },
      'GET /api/v1/assets/type-counts': {
        body: {
          view: 'all',
          total: 6,
          types: [
            { product_type_id: STATION, count: 2 },
            { product_type_id: LAPTOP, count: 3 },
            { product_type_id: PHONE, count: 1 },
          ],
        },
      },
      'GET /api/v1/list-settings/assets': { body: { list_key: 'assets', views: [savedView] } },
      'GET /api/v1/list-settings/assets/views/all': { body: noSetting('all') },
      ...routes,
    },
  });
}

describe('console: asset views and tree (WP-049b s4a)', () => {
  it('a branch counts its own types and every type below it', () => {
    const counts = branchCounts(
      [{ ...types[0], children: [types[1], types[2]] }, { ...types[3] }] as never,
      new Map([
        [STATION, 2],
        [LAPTOP, 3],
        [PHONE, 1],
      ]),
    );
    expect(counts.get(COMPUTER)).toBe(5);
    expect(counts.get(STATION)).toBe(2);
    expect(counts.get(PHONE)).toBe(1);
  });

  it('the tree is a WAI-ARIA tree: arrows, Home/End, Enter lists a node and its types', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = viewsApi();
    restore = fake.restore;
    render(<App />);
    const tree = await screen.findByRole('tree', { name: 'Product types' });
    const all = within(tree).getByTestId('asset-tree-all');
    await waitFor(() => {
      expect(within(tree).getByTestId(`asset-tree-count-${COMPUTER}`).textContent).toContain(
        '5 assets',
      );
    });
    // One row in the tab order at a time (roving tabindex).
    expect(all.getAttribute('tabindex')).toBe('0');
    const computer = within(tree).getByTestId(`asset-tree-${COMPUTER}`);
    expect(computer.getAttribute('tabindex')).toBe('-1');
    expect(computer.getAttribute('aria-expanded')).toBe('true');
    expect(computer.getAttribute('aria-level')).toBe('1');
    all.focus();
    fireEvent.keyDown(all, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(computer);
    fireEvent.keyDown(computer, { key: 'ArrowRight' }); // open: to the first child
    const station = within(tree).getByTestId(`asset-tree-${STATION}`);
    expect(document.activeElement).toBe(station);
    expect(station.getAttribute('aria-level')).toBe('2');
    fireEvent.keyDown(station, { key: 'ArrowLeft' }); // a leaf: to its parent
    expect(document.activeElement).toBe(computer);
    fireEvent.keyDown(computer, { key: 'ArrowLeft' }); // close the branch
    expect(computer.getAttribute('aria-expanded')).toBe('false');
    expect(within(tree).queryByTestId(`asset-tree-${STATION}`)).toBeNull();
    fireEvent.keyDown(computer, { key: 'End' });
    expect(document.activeElement).toBe(within(tree).getByTestId(`asset-tree-${PHONE}`));
    fireEvent.keyDown(within(tree).getByTestId(`asset-tree-${PHONE}`), { key: 'Home' });
    expect(document.activeElement).toBe(all);
    fireEvent.keyDown(all, { key: 'ArrowDown' });
    fireEvent.keyDown(computer, { key: 'Enter' });
    await waitFor(() => {
      expect(
        fake
          .find('GET', '/api/v1/assets')
          .some((call) => call.url.searchParams.get('product_type') === COMPUTER),
      ).toBe(true);
    });
    expect(computer.getAttribute('aria-selected')).toBe('true');
  });

  it('typeahead: a key moves to the next row starting with it, wrapping; quick keys make a prefix', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = viewsApi();
    restore = fake.restore;
    render(<App />);
    const tree = await screen.findByRole('tree', { name: 'Product types' });
    const row = (id: string) => within(tree).getByTestId(`asset-tree-${id}`);
    await waitFor(() => {
      expect(row(PHONE)).toBeTruthy();
    });
    const all = row('all');
    all.focus();
    fireEvent.keyDown(all, { key: 'L' }); // any case
    expect(document.activeElement).toBe(row(LAPTOP));
    await new Promise((done) => setTimeout(done, 600)); // past the prefix window
    fireEvent.keyDown(row(LAPTOP), { key: 'c' }); // wraps past the end to Computer
    expect(document.activeElement).toBe(row(COMPUTER));
    await new Promise((done) => setTimeout(done, 600));
    fireEvent.keyDown(row(COMPUTER), { key: 'p' });
    fireEvent.keyDown(row(PHONE), { key: 'h' }); // "ph": still Phone
    expect(document.activeElement).toBe(row(PHONE));
    await new Promise((done) => setTimeout(done, 600));
    fireEvent.keyDown(row(PHONE), { key: 'z' }); // nothing starts with it: focus stays
    expect(document.activeElement).toBe(row(PHONE));
  });

  it("typeahead matches in the person's language: Arabic and Urdu by their first letter", () => {
    expect(startsWith('Laptop', 'LA', 'en')).toBe(true);
    expect(startsWith('Écran', 'é', 'fr')).toBe(true);
    expect(startsWith('Laptop', 'lb', 'en')).toBe(false);
    expect(startsWith('حاسوب محمول', 'ح', 'ar')).toBe(true);
    expect(startsWith('حاسوب محمول', 'حز', 'ar')).toBe(true); // first letter only
    expect(startsWith('لیپ ٹاپ', 'ل', 'ur')).toBe(true);
    expect(startsWith('لیپ ٹاپ', 'ح', 'ur')).toBe(false);
  });

  it('shows the default columns with names, and favourites first in the view picker', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = viewsApi();
    restore = fake.restore;
    render(<App />);
    const row = (await screen.findByTestId(`asset-row-${asset.id}`)).closest('tr');
    const cells = within(row as HTMLElement);
    expect(cells.getByText('Aisha Khan')).toBeTruthy();
    expect(cells.getByText('OptiPlex 7010')).toBeTruthy();
    expect(cells.getByText('Workstation')).toBeTruthy();
    // Widths are kept per person and view in the shared store.
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/list-settings/assets/views/all').length).toBeGreaterThan(0);
    });
    fireEvent.mouseDown(within(screen.getByTestId('assets-view')).getByRole('combobox'));
    const options = await screen.findAllByRole('option');
    expect(options[0]?.textContent).toContain('Finance laptops'); // the starred one leads
  });

  it('a built-in view and a saved view filter the list on the server', async () => {
    window.history.pushState({}, '', '/assets?view=warranty_expiring');
    const fake = viewsApi({
      'GET /api/v1/list-settings/assets/views/warranty_expiring': {
        body: noSetting('warranty_expiring'),
      },
      [`GET /api/v1/list-settings/assets/views/${savedView.view_key}`]: { body: savedView },
    });
    restore = fake.restore;
    render(<App />);
    await waitFor(() => {
      expect(
        fake
          .find('GET', '/api/v1/assets')
          .some((call) => call.url.searchParams.get('view') === 'warranty_expiring'),
      ).toBe(true);
    });
    window.history.pushState({}, '', `/assets?view=${savedView.view_key}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => {
      expect(
        fake
          .find('GET', '/api/v1/assets')
          .some((call) => call.url.searchParams.get('filter') === JSON.stringify(savedView.filter)),
      ).toBe(true);
    });
  });

  it('saves the list as a view and stars a built-in view from the views drawer', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = viewsApi({
      'POST /api/v1/list-settings/assets/saved-views': {
        status: 201,
        body: { ...savedView, view_key: 'custom:01900000-0000-7000-8000-0000000b0002' },
      },
      'GET /api/v1/list-settings/assets/views/mine': { body: noSetting('mine') },
      'PUT /api/v1/list-settings/assets/views/mine': {
        body: { ...noSetting('mine'), favourite: true, version: 1 },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('assets-views-open'));
    const drawer = await screen.findByTestId('assets-views-drawer');
    fireEvent.change(within(drawer).getByTestId('assets-view-name'), {
      target: { value: 'My stations' },
    });
    fireEvent.click(within(drawer).getByTestId('assets-view-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/list-settings/assets/saved-views')).toHaveLength(1);
    });
    const [made] = fake.find('POST', '/api/v1/list-settings/assets/saved-views');
    expect(made?.headers.get('Idempotency-Key')).toBeTruthy();
    expect((made?.body as { name: string }).name).toBe('My stations');
    const star = within(drawer).getByTestId('assets-view-star-mine');
    expect(star.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(star);
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/list-settings/assets/views/mine')).toHaveLength(1);
    });
    const [put] = fake.find('PUT', '/api/v1/list-settings/assets/views/mine');
    expect((put?.body as { favourite: boolean }).favourite).toBe(true);
  });

  it('raises a work item with the asset and its holder filled in', () => {
    expect(raisePath('incident', 'tpl-1', asset)).toBe(
      `/incidents/new?template=tpl-1&asset=${asset.id}&requester=${asset.owner_user_id ?? ''}`,
    );
    expect(raisePath('service_request', 'item-1', asset)).toContain('/requests/new?item=item-1');
    expect(raisePath('change', 'tpl-2', asset)).not.toContain('asset=');
  });

  it('the linked records panel stays hidden while work items offer no links', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = viewsApi({
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"1"' } },
      [`GET /api/v1/assets/${asset.id}/history`]: { body: { items: [], next_cursor: null } },
      [`GET /api/v1/assets/${asset.id}/linked`]: { body: { available: false, kinds: [] } },
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('asset-heading');
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/assets/${asset.id}/linked`).length).toBeGreaterThan(0);
    });
    expect(screen.queryByTestId('asset-linked-section')).toBeNull();
  });

  it('with links available, counts what you may see per kind', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}`);
    const fake = viewsApi({
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"1"' } },
      [`GET /api/v1/assets/${asset.id}/history`]: { body: { items: [], next_cursor: null } },
      [`GET /api/v1/assets/${asset.id}/linked`]: {
        body: { available: true, kinds: [{ kind: 'incident', still_worked: 1, total: 4 }] },
      },
    });
    restore = fake.restore;
    render(<App />);
    const counter = await screen.findByTestId('asset-linked-incident');
    expect(counter.textContent).toContain('1 still worked of 4');
  });
});
