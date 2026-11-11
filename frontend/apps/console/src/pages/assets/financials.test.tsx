import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { AssetFinancials, AssetNote, AssetRecord } from '@supportx/api-client';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-049b s2: the asset's Financials tab (REQ-AST-036..038), notes (REQ-AST-050) and the
// history's filters (REQ-AST-049).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const asset: AssetRecord = {
  id: '01900000-0000-7000-8000-00000000f501',
  name: 'Laptop L1',
  loanable: false,
  product_id: '01900000-0000-7000-8000-00000000e001',
  product_type_id: '01900000-0000-7000-8000-00000000c001',
  state_id: '01900000-0000-7000-8000-00000000a001',
  tag: 'AST-41',
  serial_number: null,
  discovered_serial: null,
  barcode: null,
  vendor_id: null,
  site_id: null,
  location: null,
  purchase_order_id: null,
  purchase_price: '1200.00',
  purchase_tax: null,
  purchase_total: '1200.00',
  currency: 'USD',
  acquired_on: '2025-11-01',
  warranty_expires_on: null,
  expires_on: null,
  description: null,
  cost_centre: 'CC-10',
  gl_code: 'GL-6100',
  custom: {},
  created_at: '2025-11-01T00:00:00Z',
  updated_at: '2026-11-05T00:00:00Z',
  version: 3,
};
const money: AssetFinancials = {
  asset_id: asset.id,
  asset_version: 3,
  currency: 'USD',
  purchase_currency: 'USD',
  currency_differs: false,
  on: '2026-11-11',
  purchase: '1200.00',
  operational: '200.00',
  disposal: '0.00',
  total_cost: '1400.00',
  book_value: '800.00',
  cost_centre: 'CC-10',
  gl_code: 'GL-6100',
  depreciation: {
    method: 'straight_line',
    method_from: 'product',
    useful_life_years: 3,
    life_from: 'asset',
    salvage_value: null,
    salvage_from: null,
    starts_on: '2025-11-01',
    own_method: null,
    own_useful_life_years: 3,
    own_salvage_value: null,
    schedule: [
      {
        year: 1,
        starts_on: '2025-11-01',
        opening: '1200.00',
        depreciation: '400.00',
        closing: '800.00',
      },
      {
        year: 2,
        starts_on: '2026-11-01',
        opening: '800.00',
        depreciation: '400.00',
        closing: '400.00',
      },
      {
        year: 3,
        starts_on: '2027-11-01',
        opening: '400.00',
        depreciation: '400.00',
        closing: '0.00',
      },
    ],
  },
  costs: [
    {
      id: 'cost-1',
      asset_id: asset.id,
      kind: 'service',
      incurred_on: '2026-10-01',
      amount: '200.00',
      description: 'New battery',
      created_at: '2026-10-01T09:00:00Z',
      created_by: null,
      version: 2,
    },
  ],
};
const note: AssetNote = {
  id: 'note-1',
  asset_id: asset.id,
  body: '<p>Replaced the fan</p>',
  author_id: '01900000-0000-7000-8000-000000000101',
  author_name: 'Tariq Technician',
  mentioned_ids: [],
  created_at: '2026-11-02T10:00:00Z',
  edited_at: '2026-11-03T10:00:00Z',
  deleted_at: null,
  deleted_by_name: null,
  may_change: true,
  version: 2,
};

function api(roles: string[], routes = {}) {
  return consoleApi({
    me: fakeSession({ roles }),
    routes: {
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"3"' } },
      [`GET /api/v1/assets/${asset.id}/history`]: { body: { items: [], next_cursor: null } },
      [`GET /api/v1/assets/${asset.id}/financials`]: { body: money },
      [`GET /api/v1/assets/${asset.id}/notes`]: { body: [note] },
      [`GET /api/v1/files/records/asset/${asset.id}`]: { body: [] },
      'GET /api/v1/assets/states': { body: [] },
      'GET /api/v1/assets/product-types': { body: [] },
      ...routes,
    },
  });
}

describe('asset financials (REQ-AST-036..038)', () => {
  it('shows the four totals, where each depreciation setting came from, and the schedule', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=financials`);
    const fake = api(['tenant_admin']);
    restore = fake.restore;
    render(<App />);
    const tab = await screen.findByTestId('asset-financials');
    expect(within(tab).getByTestId('asset-fin-purchase').textContent).toBe('$1,200.00');
    expect(within(tab).getByTestId('asset-fin-book-value').textContent).toBe('$800.00');
    expect(within(tab).getByTestId('asset-fin-operational').textContent).toBe('$200.00');
    expect(within(tab).getByTestId('asset-fin-total').textContent).toBe('$1,400.00');
    // AC2: the method came from the product, the life was set on the asset.
    expect(within(tab).getByTestId('asset-depreciation-method-shown').textContent).toBe(
      'Straight lineFrom the product',
    );
    expect(within(tab).getByTestId('asset-terms-from-asset').textContent).toBe('Set on this asset');
    const schedule = within(tab).getByTestId('asset-depreciation-schedule');
    expect(within(schedule).getByText('Year 3')).toBeTruthy();
    expect(within(schedule).getAllByText('$400.00').length).toBeGreaterThan(0);
    // Cost lines, by their kind's label (never the code).
    const costs = within(tab).getByTestId('asset-costs-table');
    expect(within(costs).getByText('Service')).toBeTruthy();
    expect(within(costs).getByText('New battery')).toBeTruthy();
    // The side panel shows the value too, and the properties the cost centre and GL code.
    expect((await screen.findByTestId('asset-panel-book-value')).textContent).toBe('$800.00');
    expect(screen.getByText('CC-10')).toBeTruthy();
    expect(screen.getByText('GL-6100')).toBeTruthy();
  });

  it('adds a cost line with an Idempotency-Key and changes one with If-Match', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=financials`);
    const fake = api(['tenant_admin'], {
      [`POST /api/v1/assets/${asset.id}/costs`]: { status: 201, body: money.costs[0] },
      [`DELETE /api/v1/assets/${asset.id}/costs/cost-1`]: { status: 204 },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-cost-add'));
    // The shared short-form dialog (EditDialog): Save waits for the amount, and says so.
    const dialog = await screen.findByTestId('asset-cost-dialog');
    expect(within(dialog).getByTestId('edit-ok').hasAttribute('disabled')).toBe(true);
    expect(within(dialog).getByLabelText('Save: Enter the amount first.')).toBeTruthy();
    // The day comes from the shared date field, today by default.
    expect(within(dialog).getByTestId('asset-cost-date')).toBeTruthy();
    fireEvent.change(within(dialog).getByTestId('asset-cost-amount'), {
      target: { value: '75.50' },
    });
    fireEvent.change(within(dialog).getByTestId('asset-cost-description'), {
      target: { value: 'Courier' },
    });
    fireEvent.click(within(dialog).getByTestId('edit-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/assets/${asset.id}/costs`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/assets/${asset.id}/costs`);
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(sent?.body).toMatchObject({ kind: 'service', amount: '75.5', description: 'Courier' });
    expect(sent?.body).toHaveProperty('incurred_on', expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/));
    // The row's actions (RowActions): Edit as a link, Delete in the row's "…" menu, confirmed.
    const costs = screen.getByTestId('asset-costs-table');
    expect(within(costs).getByRole('button', { name: 'Edit' })).toBeTruthy();
    fireEvent.click(
      within(costs).getByRole('button', { name: /^More actions for Service cost on / }),
    );
    fireEvent.click(await screen.findByTestId('asset-cost-delete-cost-1'));
    fireEvent.click(await screen.findByTestId('asset-cost-delete-confirm'));
    await waitFor(() => {
      expect(fake.find('DELETE', `/api/v1/assets/${asset.id}/costs/cost-1`)).toHaveLength(1);
    });
    const [removed] = fake.find('DELETE', `/api/v1/assets/${asset.id}/costs/cost-1`);
    expect(removed?.headers.get('If-Match')).toBe('"2"');
  });

  it('changes a cost line from its Edit link, with If-Match', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=financials`);
    const fake = api(['tenant_admin'], {
      [`PATCH /api/v1/assets/${asset.id}/costs/cost-1`]: {
        body: { ...money.costs[0], amount: '210.00', version: 3 },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-cost-edit-cost-1'));
    const dialog = await screen.findByTestId('asset-cost-dialog');
    expect(within(dialog).getByText('Change cost')).toBeTruthy();
    fireEvent.change(within(dialog).getByTestId('asset-cost-amount'), {
      target: { value: '210' },
    });
    fireEvent.click(within(dialog).getByTestId('edit-ok'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/assets/${asset.id}/costs/cost-1`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/assets/${asset.id}/costs/cost-1`);
    expect(sent?.headers.get('If-Match')).toBe('"2"');
    expect(sent?.body).toMatchObject({ incurred_on: '2026-10-01', amount: '210' });
  });

  it('shows a dash for the total while nothing is known, in the card and the panel', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=financials`);
    const fake = api(['tenant_admin'], {
      [`GET /api/v1/assets/${asset.id}/financials`]: {
        body: {
          ...money,
          purchase: null,
          book_value: null,
          operational: '0.00',
          total_cost: '0.00',
          costs: [],
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    const tab = await screen.findByTestId('asset-financials');
    expect(within(tab).getByTestId('asset-fin-total').textContent).toBe('—');
    expect((await screen.findByTestId('asset-panel-total-cost')).textContent).toBe('—');
  });

  it('configures depreciation through the asset save, with If-Match', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=financials`);
    const fake = api(['tenant_admin'], {
      [`PATCH /api/v1/assets/${asset.id}`]: { body: { ...asset, version: 4 } },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('asset-depreciation-open'));
    const dialog = await screen.findByTestId('asset-depreciation-dialog');
    fireEvent.change(within(dialog).getByTestId('asset-depreciation-salvage'), {
      target: { value: '100' },
    });
    fireEvent.click(within(dialog).getByTestId('edit-ok'));
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/assets/${asset.id}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/assets/${asset.id}`);
    expect(sent?.headers.get('If-Match')).toBe('"3"');
    expect(sent?.body).toMatchObject({
      depreciation_method: null,
      useful_life_years: 3,
      salvage_value: '100',
    });
  });

  it('shows no money to a technician: no tab, no value in the panel, no request for it', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=financials`);
    const fake = api(['technician']);
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('asset-page')).toBeTruthy();
    expect(screen.queryByTestId('asset-financials')).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Financials' })).toBeNull();
    expect(screen.queryByTestId('asset-panel-book-value')).toBeNull();
    expect(fake.find('GET', `/api/v1/assets/${asset.id}/financials`)).toHaveLength(0);
  });
});

describe('asset notes and history (REQ-AST-049, 050)', () => {
  it("lists notes with the edited marker and a deleted note's line", async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=notes`);
    const fake = api(['technician'], {
      [`GET /api/v1/assets/${asset.id}/notes`]: {
        body: [
          note,
          {
            ...note,
            id: 'note-2',
            body: null,
            deleted_at: '2026-11-04T10:00:00Z',
            deleted_by_name: 'Aisha Admin',
            may_change: false,
          },
        ],
      },
      [`GET /api/v1/assets/${asset.id}/notes/note-1/history`]: {
        body: [
          {
            version: 2,
            kind: 'updated',
            actor_name: 'Tariq Technician',
            occurred_at: '2026-11-03T10:00:00Z',
            body: '<p>Replaced the fan</p>',
            previous: '<p>Fan noisy</p>',
          },
          {
            version: 1,
            kind: 'created',
            actor_name: 'Tariq Technician',
            occurred_at: '2026-11-02T10:00:00Z',
            body: '<p>Fan noisy</p>',
            previous: null,
          },
        ],
      },
    });
    restore = fake.restore;
    render(<App />);
    const list = await screen.findByTestId('asset-notes-list');
    expect(await within(list).findByText('Replaced the fan')).toBeTruthy();
    expect(within(list).getByTestId('asset-note-deleted').textContent).toContain('Aisha Admin');
    fireEvent.click(within(list).getByTestId('asset-note-edited'));
    const versions = await screen.findByTestId('asset-note-versions');
    expect(await within(versions).findByText('Fan noisy')).toBeTruthy();
  });

  it("edits from the note's Edit link and deletes from its menu, confirmed, with If-Match", async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=notes`);
    const fake = api(['technician'], {
      [`DELETE /api/v1/assets/${asset.id}/notes/note-1`]: { status: 204 },
    });
    restore = fake.restore;
    render(<App />);
    const list = await screen.findByTestId('asset-notes-list');
    // RowActions: no side-by-side Edit and Delete buttons.
    expect(within(list).getByRole('button', { name: 'Edit' })).toBeTruthy();
    expect(within(list).queryByRole('button', { name: 'Delete' })).toBeNull();
    fireEvent.click(
      within(list).getByRole('button', { name: /^More actions for Note by Tariq Technician/ }),
    );
    fireEvent.click(await screen.findByTestId('asset-note-delete-note-1'));
    fireEvent.click(await screen.findByTestId('asset-note-delete-confirm'));
    await waitFor(() => {
      expect(fake.find('DELETE', `/api/v1/assets/${asset.id}/notes/note-1`)).toHaveLength(1);
    });
    const [removed] = fake.find('DELETE', `/api/v1/assets/${asset.id}/notes/note-1`);
    expect(removed?.headers.get('If-Match')).toBe('"2"');
    fireEvent.click(within(list).getByTestId('asset-note-edit-note-1'));
    expect(await screen.findByTestId('asset-note-editor')).toBeTruthy();
  });

  it('keeps the sub-view in the bar and the other filters in the drawer', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=history`);
    const fake = api(['technician']);
    restore = fake.restore;
    render(<App />);
    const bar = await screen.findByTestId('asset-history-filters');
    expect(within(bar).getByTestId('asset-history-view')).toBeTruthy();
    // Field, source, person and days live in the drawer, not the bar (D-124).
    expect(screen.queryByTestId('asset-history-field')).toBeNull();
    expect(screen.queryByTestId('asset-history-source')).toBeNull();
    fireEvent.click(within(bar).getByTestId('asset-history-filters-filters'));
    const drawer = await screen.findByTestId('asset-history-drawer');
    const source = within(drawer).getByTestId('asset-history-source');
    fireEvent.mouseDown(source.querySelector('.ant-select-selector') ?? source);
    const option = await waitFor(() => {
      const found = screen
        .getAllByText('through the API')
        .filter((n) => n.closest('.ant-select-item-option') !== null);
      const last = found.at(-1);
      if (last === undefined) throw new Error('no option');
      return last;
    });
    fireEvent.click(option);
    await waitFor(() => {
      const asked = fake.find('GET', `/api/v1/assets/${asset.id}/history`);
      expect(asked.some((r) => r.url.searchParams.get('source') === 'api')).toBe(true);
    });
    // The bar counts the drawer's filters and offers to clear them.
    expect(within(bar).getByTestId('asset-history-clear')).toBeTruthy();
    expect(within(bar).getByText('1')).toBeTruthy();
  });

  it('narrows the history to the state sub-view', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=history`);
    const fake = api(['technician']);
    restore = fake.restore;
    render(<App />);
    const view = await screen.findByTestId('asset-history-view');
    fireEvent.click(within(view).getByText('State'));
    await waitFor(() => {
      const asked = fake.find('GET', `/api/v1/assets/${asset.id}/history`);
      expect(asked.some((r) => r.url.searchParams.get('view') === 'state')).toBe(true);
    });
    expect(await screen.findByText('No changes match these filters.')).toBeTruthy();
  });
});
