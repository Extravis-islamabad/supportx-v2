import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type {
  AssetBooking,
  AssetConsumableDetail,
  AssetMovement,
  AssetRecord,
} from '@supportx/api-client';

import { ApiError } from '@supportx/api-client';
import { label, stripIsolates, type LabelParams } from '@supportx/labels';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';
import { problemText } from './problemText';
import { plainQuantity } from './quantity';

// WP-049b s1: consumables (REQ-AST-033, 034), minimum stock (035), bookings (032), and the loan
// register's display ID, department, site and filters (030).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const SITE = '01900000-0000-7000-8000-0000000051a1';
const consumable: AssetConsumableDetail = {
  id: '01900000-0000-7000-8000-00000000c501',
  product_id: '01900000-0000-7000-8000-00000000e501',
  product_name: 'Toner 26A',
  product_type_id: '01900000-0000-7000-8000-00000000c001',
  batch_tracked: true,
  barcode: 'TN-26A',
  vendor_id: null,
  unit_cost: '12.50',
  comment: null,
  total: '6.000',
  stocks: [
    {
      id: 'st-1',
      site_id: SITE,
      location: 'Store 2',
      quantity: '2.000',
      minimum: '5.000',
      low: true,
      version: 4,
    },
    {
      id: 'st-2',
      site_id: null,
      location: null,
      quantity: '4.000',
      minimum: null,
      low: false,
      version: 1,
    },
  ],
  batches: [
    {
      id: 'b-1',
      stock_id: 'st-1',
      site_id: SITE,
      lot_number: 'L-100',
      reference: null,
      manufactured_on: '2025-01-01',
      expires_on: '2026-01-01',
      quantity: '2.000',
      expired: true,
    },
  ],
  version: 2,
};
const received: AssetMovement = {
  id: 'm-1',
  consumable_id: consumable.id,
  stock_id: 'st-1',
  batch_id: 'b-1',
  kind: 'receive',
  quantity: '2.000',
  balance_after: '2.000',
  happened_on: '2026-11-10',
  recipient_kind: null,
  recipient_id: null,
  work_item_id: null,
  unit_cost: '12.50',
  comment: 'Delivery 7',
  created_at: '2026-11-10T09:00:00Z',
  created_by: null,
};

function api(routes = {}, locale: 'en' | 'ar' | 'ur' = 'en') {
  return consoleApi({
    me: fakeSession({ roles: ['tenant_admin'], locale }),
    routes: {
      'GET /api/v1/assets/consumables': { body: [consumable] },
      [`GET /api/v1/assets/consumables/${consumable.id}`]: {
        body: consumable,
        headers: { ETag: '"2"' },
      },
      [`GET /api/v1/assets/consumables/${consumable.id}/ledger`]: { body: [received] },
      'GET /api/v1/organization/sites': { body: [{ id: SITE, name: 'Head office' }] },
      'GET /api/v1/assets/product-types': { body: [] },
      'GET /api/v1/assets/products': {
        body: { items: [], next_cursor: null, has_more: false, estimated_total: 0 },
      },
      ...routes,
    },
  });
}

describe('quantities', () => {
  it('show as people write them, never through a float', () => {
    expect(plainQuantity('20.000')).toBe('20');
    expect(plainQuantity('2.500')).toBe('2.5');
    expect(plainQuantity('0.000')).toBe('0');
    expect(plainQuantity('-1.000')).toBe('-1');
  });
});

describe('console: consumables', () => {
  it('lists consumables with their stock per site and flags one below its minimum', async () => {
    window.history.pushState({}, '', '/assets/consumables');
    const fake = api();
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId(`consumable-${consumable.id}`)).toBeTruthy();
    expect(screen.getByTestId(`consumable-total-${consumable.id}`).textContent).toBe('6');
    // 2 against a minimum of 5: below it, never "At minimum" (QA 2026-11-11 F-15).
    expect(screen.getByTestId('consumable-low-st-1').textContent).toBe('Below minimum');
    expect(screen.getByText('Batches')).toBeTruthy();
    // The site filter reads as a filter, not as a row's "No site".
    const filter = screen.getByTestId('consumables-site');
    expect(within(filter).getByText('All sites')).toBeTruthy();
    expect(within(filter).queryByText('No site')).toBeNull();
  });

  it('stock by site reads "<site>: <amount>" in order, in Arabic too (QA 2026-11-12 V-14)', async () => {
    for (const locale of ['en', 'ar'] as const) {
      window.history.pushState({}, '', '/assets/consumables');
      const fake = api({}, locale);
      restore = fake.restore;
      const { unmount } = render(<App />);
      const line = await screen.findByTestId('consumable-stock-st-1');
      await waitFor(() => {
        expect(stripIsolates(line.textContent)).toContain('Head office: 2');
      });
      if (locale === 'ar') {
        expect(document.documentElement.getAttribute('dir')).toBe('rtl');
        // Each value in its own isolate (FSI … PDI): the colon stays after the site in RTL.
        expect(line.textContent).toContain('\u2068Head office\u2069: \u20682\u2069');
      }
      unmount();
      fake.restore();
    }
  });

  it('says below or at the minimum as it is, and the unit cost with its currency (F-15)', async () => {
    window.history.pushState({}, '', `/assets/consumables/${consumable.id}`);
    const fake = api();
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('consumable-heading')).toBeTruthy();
    expect(screen.getByTestId('stock-low-st-1').textContent).toBe('Below minimum');
    expect(screen.getByTestId('consumable-low').textContent).toBe('Below minimum');
    // The base currency comes from the instance settings (USD in the test console).
    await waitFor(() => {
      expect(screen.getByTestId('consumable-unit-cost').textContent).toContain('$12.50');
    });
  });

  it('a stock exactly at its minimum says "At minimum"', async () => {
    window.history.pushState({}, '', `/assets/consumables/${consumable.id}`);
    const atMinimum = {
      ...consumable,
      stocks: consumable.stocks.map((s) => (s.id === 'st-1' ? { ...s, quantity: '5.000' } : s)),
    };
    const fake = api({
      [`GET /api/v1/assets/consumables/${consumable.id}`]: {
        body: atMinimum,
        headers: { ETag: '"2"' },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('stock-low-st-1')).toBeTruthy();
    expect(screen.getByTestId('stock-low-st-1').textContent).toBe('At minimum');
    expect(screen.getByTestId('consumable-low').textContent).toBe('At minimum');
  });

  it('shows stock, an expired batch flagged, and the ledger', async () => {
    window.history.pushState({}, '', `/assets/consumables/${consumable.id}`);
    const fake = api();
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('consumable-heading')).toBeTruthy();
    expect(screen.getByTestId('stock-quantity-st-1').textContent).toBe('2');
    expect(screen.getByTestId('batch-expired-b-1').textContent).toBe('Expired');
    fireEvent.click(screen.getByRole('tab', { name: 'Ledger' }));
    const ledger = await screen.findByTestId('consumable-ledger');
    expect(await within(ledger).findByText('Received')).toBeTruthy();
    expect(within(ledger).getByText('Delivery 7')).toBeTruthy();
  });

  it('the Allocate dialog says what is still missing before it can be sent', async () => {
    window.history.pushState({}, '', `/assets/consumables/${consumable.id}`);
    const fake = api();
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('consumable-heading');
    fireEvent.click(screen.getByRole('button', { name: 'Allocate' }));
    const dialog = await screen.findByTestId('stock-dialog');
    expect(within(dialog).getByTestId('stock-dialog-save').hasAttribute('disabled')).toBe(true);
    expect(dialog.textContent).toContain('Allocate to');
    expect(dialog.textContent).toContain('Batch'); // batch-tracked: the lot is asked for
    expect(
      fake.find('POST', `/api/v1/assets/consumables/${consumable.id}/allocations`),
    ).toHaveLength(0);
  });

  it('a refusal reads as words: the amount available, the next free day, the fixed batch choice', () => {
    const t = (key: string, params?: LabelParams) => stripIsolates(label(key, 'en', params));
    const short = new ApiError(
      409,
      problem(409, 'asset_stock_short', { params: { available: '2' } }),
      null,
    );
    expect(problemText(t, short)).toBe('Not enough in stock: only 2 available.');
    const taken = new ApiError(
      409,
      problem(409, 'asset_booking_taken', { params: { next_free: '2026-12-02T09:00:00Z' } }),
      null,
    );
    expect(
      problemText(t, taken, (_, given) => ({ ...given, next_free: '2 Dec 2026, 09:00' })),
    ).toBe('That time is already taken. The next free day starts 2 Dec 2026, 09:00.');
    const fixed = new ApiError(409, problem(409, 'asset_consumable_batch_tracking_fixed'), null);
    expect(problemText(t, fixed)).toContain('cannot be switched later');
  });

  it('says the list is empty only once it has loaded, never under the spinner', async () => {
    window.history.pushState({}, '', '/assets/consumables');
    let answer: (reply: { body: unknown }) => void = () => undefined;
    const fake = api({
      'GET /api/v1/assets/consumables': () =>
        new Promise<{ body: unknown }>((resolve) => {
          answer = resolve;
        }),
    });
    restore = fake.restore;
    render(<App />);
    const table = await screen.findByTestId('consumables');
    expect(within(table).queryByText('No consumables kept yet.')).toBeNull();
    answer({ body: [] });
    expect(await within(table).findByText('No consumables kept yet.')).toBeTruthy();
  });

  it('the ledger says nothing has moved only once it has loaded', async () => {
    window.history.pushState({}, '', `/assets/consumables/${consumable.id}`);
    const fake = api({
      [`GET /api/v1/assets/consumables/${consumable.id}/ledger`]: () =>
        new Promise<{ body: unknown }>(() => undefined),
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('consumable-heading');
    fireEvent.click(screen.getByRole('tab', { name: 'Ledger' }));
    const ledger = await screen.findByTestId('consumable-ledger');
    expect(within(ledger).queryByText('Nothing has moved yet.')).toBeNull();
    expect(within(ledger).getByTestId('empty-loading')).toBeTruthy();
  });

  it('the record names its path in the top bar and says once, as a notice, that none is left', async () => {
    window.history.pushState({}, '', `/assets/consumables/${consumable.id}`);
    const empty = {
      ...consumable,
      total: '0.000',
      stocks: consumable.stocks.map((s) => ({ ...s, quantity: '0.000' })),
    };
    const fake = api({
      [`GET /api/v1/assets/consumables/${consumable.id}`]: {
        body: empty,
        headers: { ETag: '"2"' },
      },
    });
    restore = fake.restore;
    render(<App />);
    const page = await screen.findByTestId('consumable-page');
    await waitFor(() => {
      expect(document.title).toContain('Toner 26A');
    });
    expect(document.title).toContain('Consumables');
    // The path is the crumbs' job now, not a link in the record's header.
    expect(within(page).queryByRole('link', { name: 'Consumables' })).toBeNull();
    expect(screen.getByTestId('consumable-all-out').textContent).toContain(
      'None left at any site.',
    );
  });

  it('batch tracking cannot be switched: the refusal reads as the reason', async () => {
    window.history.pushState({}, '', '/assets/consumables');
    const fake = api({
      'POST /api/v1/assets/consumables': {
        status: 409,
        body: problem(409, 'asset_consumable_exists'),
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('consumable-new-open'));
    const dialog = await screen.findByTestId('consumable-new');
    expect(dialog.textContent).toContain('Chosen now for good');
    expect(within(dialog).getByTestId('consumable-new-save').hasAttribute('disabled')).toBe(true);
  });
});

const asset: AssetRecord = {
  id: '01900000-0000-7000-8000-00000000d501',
  name: 'Projector P1',
  loanable: true,
  product_id: '01900000-0000-7000-8000-00000000e001',
  product_type_id: '01900000-0000-7000-8000-00000000c001',
  state_id: '01900000-0000-7000-8000-00000000a001',
  tag: 'AST-9',
  serial_number: null,
  discovered_serial: null,
  barcode: null,
  vendor_id: null,
  site_id: null,
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
  version: 3,
};
const BORROWER = '01900000-0000-7000-8000-00000000b501';
const booking: AssetBooking = {
  id: 'bk-1',
  asset_id: asset.id,
  borrower_id: BORROWER,
  department_id: null,
  starts_at: '2026-12-01T09:00:00Z',
  ends_at: '2026-12-01T17:00:00Z',
  status: 'booked',
  loan_id: null,
  channel: 'portal',
  comment: 'Training day',
  version: 1,
};

describe('console: bookings and loans', () => {
  it("the asset's bookings tab hands a booking over with If-Match", async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=bookings`);
    const fake = api({
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"3"' } },
      [`GET /api/v1/assets/${asset.id}/history`]: { body: { items: [], next_cursor: null } },
      'GET /api/v1/assets/states': { body: [] },
      'GET /api/v1/assets/bookings': { body: [booking] },
      [`GET /api/v1/users/${BORROWER}`]: { body: { id: BORROWER, display_name: 'Sara Field' } },
      'POST /api/v1/assets/bookings/bk-1/handover': {
        body: { booking: { ...booking, status: 'handed_over', loan_id: 'l-9' }, loan: {} },
      },
    });
    restore = fake.restore;
    render(<App />);
    const table = await screen.findByTestId('asset-bookings-table');
    expect(await within(table).findByText('Sara Field')).toBeTruthy();
    expect(screen.getByTestId('asset-booking-status-bk-1').textContent).toBe('Booked');
    expect(within(table).getByText('Booked in the portal')).toBeTruthy();
    fireEvent.click(screen.getByTestId('asset-booking-handover-bk-1'));
    const confirm = await screen.findByRole('tooltip');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Hand over' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/bookings/bk-1/handover')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/assets/bookings/bk-1/handover');
    expect(sent?.headers.get('If-Match')).toBe('"1"');
  });

  it("the asset's bookings say there are none only once they have loaded", async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=bookings`);
    let answer: (reply: { body: unknown }) => void = () => undefined;
    const fake = api({
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"3"' } },
      [`GET /api/v1/assets/${asset.id}/history`]: { body: { items: [], next_cursor: null } },
      'GET /api/v1/assets/states': { body: [] },
      'GET /api/v1/assets/bookings': () =>
        new Promise<{ body: unknown }>((resolve) => {
          answer = resolve;
        }),
    });
    restore = fake.restore;
    render(<App />);
    const table = await screen.findByTestId('asset-bookings-table');
    expect(within(table).queryByText('No bookings ahead.')).toBeNull();
    answer({ body: [] });
    expect(await within(table).findByText('No bookings ahead.')).toBeTruthy();
  });

  it('the loan register shows the display ID, the department and site, and filters by status', async () => {
    const department = '01900000-0000-7000-8000-00000000dd01';
    const loan = {
      id: 'l-1',
      display_id: 'LN-12',
      borrower_id: BORROWER,
      department_id: department,
      site_id: SITE,
      booking_id: null,
      starts_at: '2026-11-01T09:00:00Z',
      due_at: '2026-11-08T17:00:00Z',
      closed_at: null,
      comment: null,
      status: 'open',
      outstanding: [asset.id],
      assets: [
        { id: asset.id, tag: 'AST-9', name: 'Projector P1', returned_at: null, outcome: null },
      ],
      version: 1,
    };
    window.history.pushState({}, '', '/assets/loans');
    const fake = api({
      'GET /api/v1/assets/loans': { body: [loan] },
      [`GET /api/v1/users/${BORROWER}`]: { body: { id: BORROWER, display_name: 'Sara Field' } },
      'GET /api/v1/organization/departments': {
        body: [{ id: department, name: 'Finance', disabled: false }],
      },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('asset-loan-id-l-1')).textContent).toBe('LN-12');
    const table = screen.getByTestId('asset-loans');
    expect(await within(table).findByText('Collected by Sara Field')).toBeTruthy();
    expect(await within(table).findByText('Head office')).toBeTruthy();
    fireEvent.click(within(screen.getByTestId('asset-loans-status')).getByText('Closed'));
    await waitFor(() => {
      expect(
        fake
          .find('GET', '/api/v1/assets/loans')
          .some((c) => c.url.searchParams.get('status') === 'closed'),
      ).toBe(true);
    });
  });
});

describe('console: minimum stock', () => {
  it('the admin tab lists the minimums and adds one for a product type', async () => {
    const toner = {
      id: '01900000-0000-7000-8000-00000000c777',
      parent_id: null,
      api_name: 'toner_and_ink',
      names: { en: 'Toner and ink' },
      icon: null,
      category: 'non_it',
      kind: 'consumable',
      description: null,
      life_cycle_id: null,
      tag_pattern: null,
      ack_required: false,
      sort: 0,
      version: 1,
    };
    window.history.pushState({}, '', '/admin/assets?tab=stock_rules');
    const fake = api({
      'GET /api/v1/assets/product-types': { body: [toner] },
      'GET /api/v1/assets/settings': {
        body: {
          tag_pattern: 'AST-{n}',
          warranty_notice_days: 30,
          age_basis: 'acquisition_date',
          cost_includes_tax: true,
          copy_limit: 50,
          site_follows_owner: false,
          portal_own_assets_only: true,
          email_include_assets: false,
          scan_retention_months: 6,
          portal_booking: false,
          version: 1,
        },
      },
      'GET /api/v1/assets/states': { body: [] },
      'GET /api/v1/assets/life-cycles': { body: [] },
      'GET /api/v1/assets/stock-rules': {
        body: [
          {
            id: 'r-1',
            product_type_id: toner.id,
            product_id: null,
            site_id: null,
            min_quantity: '5.000',
            notify_user_ids: [BORROWER],
            create_purchase_request: false,
            reorder_quantity: null,
            version: 1,
          },
        ],
      },
    });
    restore = fake.restore;
    render(<App />);
    const table = await screen.findByTestId('stock-rules-table');
    expect(await within(table).findByText('Toner and ink')).toBeTruthy();
    expect(within(table).getByText('Every site')).toBeTruthy();
    expect(within(table).getByText('5')).toBeTruthy();
    expect(within(table).getByText('1 person')).toBeTruthy();
    fireEvent.click(screen.getByTestId('stock-rule-add'));
    const dialog = await screen.findByTestId('stock-rule-dialog');
    expect(within(dialog).getByTestId('stock-rule-save').hasAttribute('disabled')).toBe(true);
  });
});
