import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { AssetBulkJob, AssetImport, AssetRecord } from '@supportx/api-client';
import type { FakeRoute } from '@supportx/api-client/testing';
import { en } from '@supportx/labels';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';
import {
  bulkChanges,
  columnText,
  exportColumns,
  failureText,
  MONEY_COLUMNS,
  problemsCsv,
  reasonText,
} from './batch';

// WP-049b S4b: bulk actions as a job with live progress (REQ-AST-051), merging duplicates with a
// field-by-field choice and the restore warning (052), the import wizard (dry run, problems,
// run) and the export with money only for those who may see it (053).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

// A plain `t` for the pure helpers: the English label with its values filled in.
const t = ((key: string, params: Record<string, string | number> = {}) =>
  ((en as Record<string, string>)[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(params[name] ?? ''),
  )) as never;

const ME = '01900000-0000-7000-8000-000000000101';
const STATE = '01900000-0000-7000-8000-00000000a001';
const record = (n: number, tag: string): AssetRecord => ({
  id: `01900000-0000-7000-8000-00000000d00${String(n)}`,
  name: `Laptop ${String(n)}`,
  loanable: false,
  product_id: '01900000-0000-7000-8000-00000000e001',
  product_type_id: '01900000-0000-7000-8000-0000000c0003',
  state_id: STATE,
  tag,
  serial_number: `SN-${String(n)}`,
  discovered_serial: null,
  barcode: null,
  vendor_id: null,
  site_id: null,
  owner_user_id: null,
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
});
const ONE = record(1, 'AST-1');
const TWO = record(2, 'AST-2');
const page = (items: AssetRecord[]) => ({
  items,
  next_cursor: null,
  has_more: false,
  estimated_total: items.length,
  people: {},
  parents: {},
  products: {},
});
const grant = (key: string) => ({ key, scope: 'all', scopes: ['all'], conditional: false });

function assetsApi({
  permissions = ['assets.view', 'assets.manage', 'reports.export', 'vendors.create'],
  routes = {},
  locale = 'en',
}: {
  permissions?: string[];
  routes?: Record<string, FakeRoute>;
  locale?: 'en' | 'ar' | 'ur';
} = {}) {
  return consoleApi({
    me: fakeSession(
      { roles: ['tenant_admin'], locale },
      { permissions: permissions.map(grant) as never },
    ),
    routes: {
      'GET /api/v1/assets': { body: page([ONE, TWO]) },
      'GET /api/v1/assets/trash': { body: page([TWO]) },
      'GET /api/v1/assets/product-types': { body: [] },
      'GET /api/v1/assets/states': {
        body: [
          {
            id: STATE,
            code: 'in_use',
            names: { en: 'In use' },
            category: 'in_use',
            reason_required: false,
            is_default_for_category: true,
            system: false,
            sort: 0,
            version: 1,
          },
        ],
      },
      'GET /api/v1/assets/type-counts': { body: { view: 'all', total: 2, types: [] } },
      'GET /api/v1/list-settings/assets': { body: { list_key: 'assets', views: [] } },
      'GET /api/v1/list-settings/assets/views/all': {
        body: {
          view_key: 'all',
          columns: [],
          sort: null,
          page_size: 50,
          favourite: false,
          version: null,
        },
      },
      ...routes,
    },
  });
}

async function pickBoth() {
  await screen.findByTestId(`asset-row-${ONE.id}`);
  for (const asset of [ONE, TWO]) {
    const row = screen.getByTestId(`asset-row-${asset.id}`).closest('tr');
    if (row === null) throw new Error('no row');
    fireEvent.click(within(row).getByRole('checkbox'));
  }
  await screen.findByTestId('assets-selection');
}

const job = (over: Partial<AssetBulkJob> = {}): AssetBulkJob => ({
  id: '01900000-0000-7000-8000-0000000b1001',
  action: 'move',
  status: 'queued',
  total: 2,
  processed: 0,
  done_count: 0,
  skipped_count: 0,
  results: [],
  created_at: '2026-11-11T00:00:00Z',
  started_at: null,
  finished_at: null,
  ...over,
});

describe('console: asset bulk jobs, merges, imports and export (WP-049b S4b)', () => {
  it('the job takes only what the person filled in, per action', () => {
    const empty = {
      location: '',
      costCentre: '',
      glCode: '',
      reason: '',
      holderKind: 'none' as const,
    };
    expect(bulkChanges('edit', empty)).toBeNull();
    expect(bulkChanges('edit', { ...empty, location: ' Shelf 4 ', siteId: 's1' })).toEqual({
      location: 'Shelf 4',
      site_id: 's1',
    });
    expect(bulkChanges('move', empty)).toBeNull();
    expect(bulkChanges('move', { ...empty, stateId: 'x', reason: 'Audit' })).toEqual({
      to_state_id: 'x',
      reason: 'Audit',
    });
    expect(bulkChanges('assign', empty)).toEqual({}); // back to no one
    expect(bulkChanges('assign', { ...empty, holderKind: 'user', holderId: null })).toBeNull();
    expect(bulkChanges('assign', { ...empty, holderKind: 'user', holderId: 'u' })).toEqual({
      holder_kind: 'user',
      holder_id: 'u',
    });
    expect(bulkChanges('delete', empty)).toEqual({});
  });

  it('reasons, columns and failures are words, never codes', () => {
    expect(reasonText(t, 'permission_denied', null)).toBe(en['errors.permission_denied']);
    expect(reasonText(t, 'required', 'serial_number')).toBe(en['errors.field.required']);
    expect(reasonText(t, 'asset_import_exists', 'name')).toBe(en['errors.asset_import_exists']);
    expect(reasonText(t, 'no_such_code', null)).toBe(en['errors.internal_error']);
    expect(columnText(t, 'serial_number')).toBe('Serial number');
    expect(columnText(t, 'row')).toBe('Whole row');
    expect(columnText(t, 'unheard_of')).toBe('Whole row');
    const failed = { failure: 'no_key_column', failure_detail: 'serial_number' } as AssetImport;
    expect(failureText(t, failed)).toBe('The file needs a column to match rows by: Serial number.');
    const csv = problemsCsv(t, [{ row: 4, field: 'site', code: 'site_not_found' }]);
    expect(csv.charCodeAt(0)).toBe(0xfeff); // Excel opens it as UTF-8
    expect(csv).toContain('"Row","Column","Problem"');
    expect(csv).toContain('"4","Site"');
    expect(csv).not.toContain('site_not_found');
  });

  it('money columns are exported only for those who may see money (D-157)', () => {
    expect(exportColumns(false).some((c) => MONEY_COLUMNS.includes(c))).toBe(false);
    expect(exportColumns(true)).toEqual(expect.arrayContaining(MONEY_COLUMNS));
  });

  it('a bulk move runs as a job and its progress follows live on the personal channel', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/assets');
    let current = job();
    const fake = assetsApi({
      routes: {
        'POST /api/v1/assets/bulk-jobs': { status: 202, body: job() },
        [`GET /api/v1/assets/bulk-jobs/${job().id}`]: () => ({ body: current }),
      },
    });
    restore = fake.restore;
    render(<App />);
    await pickBoth();
    fireEvent.click(screen.getByTestId('assets-bulk-open'));
    const dialog = await screen.findByTestId('asset-bulk-dialog');
    fireEvent.click(within(dialog).getByText('Change state'));
    fireEvent.mouseDown(within(dialog).getByRole('combobox'));
    fireEvent.click(await screen.findByTitle('In use'));
    fireEvent.click(screen.getByTestId('asset-bulk-start'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/bulk-jobs')).toHaveLength(1);
    });
    const sent = fake.find('POST', '/api/v1/assets/bulk-jobs')[0];
    expect(sent?.body).toEqual({
      action: 'move',
      asset_ids: [ONE.id, TWO.id],
      changes: { to_state_id: STATE },
    });
    expect(sent?.headers.get('Idempotency-Key')).not.toBeNull();
    await screen.findByTestId('asset-bulk-progress');
    current = job({
      status: 'done',
      processed: 2,
      done_count: 1,
      skipped_count: 1,
      results: [
        { id: ONE.id, tag: 'AST-1', outcome: 'done', params: {} },
        {
          id: TWO.id,
          tag: 'AST-2',
          outcome: 'skipped',
          code: 'asset_move_not_allowed',
          field: null,
          params: { allowed: 0 },
        },
      ],
    });
    act(() => {
      realtime.publish(`:user:${ME}`, { type: 'assets.bulk_progress', ids: [job().id] });
    });
    await waitFor(() => {
      expect(screen.getByTestId('asset-bulk-summary').textContent).toBe('Done: 1. Skipped: 1.');
    });
    const skipped = screen.getByTestId('asset-bulk-skipped');
    expect(skipped.textContent).toContain('AST-2');
    expect(skipped.textContent).not.toContain('asset_move_not_allowed');
  });

  it('merging two shows each field side by side and sends the choice', async () => {
    window.history.pushState({}, '', '/assets');
    const fields = [
      { field: 'name', survivor: 'Laptop 1', merged: 'Laptop 2', side: 'survivor', hidden: false },
      { field: 'location', survivor: null, merged: 'Store', side: 'merged', hidden: false },
      { field: 'purchase_price', survivor: null, merged: null, side: 'survivor', hidden: true },
    ];
    const fake = assetsApi({
      routes: {
        'GET /api/v1/assets/merge-preview': {
          body: { survivor: ONE, merged: TWO, swapped: false, fields },
        },
        'GET /api/v1/procurement/vendors': {
          body: { items: [], next_cursor: null, has_more: false },
        },
        'POST /api/v1/assets/merges': {
          status: 201,
          body: { merge_id: 'm1', survivor: ONE, mapping: [], moved: {} },
        },
        [`GET /api/v1/assets/${ONE.id}`]: { body: ONE },
      },
    });
    restore = fake.restore;
    render(<App />);
    await pickBoth();
    fireEvent.click(screen.getByTestId('assets-merge-open'));
    const table = await screen.findByTestId('asset-merge-fields');
    expect(table.textContent).toContain('Store');
    expect(table.textContent).toContain('Hidden'); // money without the right
    expect(table.textContent).not.toContain('purchase_price');
    fireEvent.click(screen.getByTestId('asset-merge-name-merged'));
    fireEvent.click(screen.getByTestId('asset-merge-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/merges')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/assets/merges')[0]?.body).toEqual({
      survivor_id: ONE.id,
      survivor_version: 3,
      merged_id: TWO.id,
      merged_version: 3,
      choices: { name: 'merged' },
    });
  });

  it('merge needs exactly two assets picked', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId(`asset-row-${ONE.id}`);
    const row = screen.getByTestId(`asset-row-${ONE.id}`).closest('tr');
    if (row === null) throw new Error('no row');
    fireEvent.click(within(row).getByRole('checkbox'));
    const merge = await screen.findByTestId('assets-merge-open');
    expect(merge.hasAttribute('disabled') || merge.getAttribute('aria-disabled') === 'true').toBe(
      true,
    );
  });

  it('restoring a merged asset warns first, then restores on confirmation', async () => {
    window.history.pushState({}, '', '/assets?view=trash');
    const fake = assetsApi({
      routes: {
        [`POST /api/v1/assets/${TWO.id}/restore`]: (call) =>
          call.url.searchParams.get('confirm_merged') === 'true'
            ? { body: TWO }
            : {
                status: 409,
                body: problem(409, 'asset_restore_merged', { params: { asset: 'AST-1' } }),
              },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId(`asset-restore-${TWO.id}`));
    const ok = await screen.findByTestId('asset-restore-merged-ok');
    expect(document.body.textContent).toContain('This asset was merged into');
    fireEvent.click(ok);
    await waitFor(() => {
      const calls = fake.find('POST', `/api/v1/assets/${TWO.id}/restore`);
      expect(calls.map((c) => c.url.searchParams.get('confirm_merged'))).toEqual(['false', 'true']);
    });
  });

  it('the import wizard: a dry run with its problems, then the run with If-Match', async () => {
    window.history.pushState({}, '', '/assets');
    const checked: AssetImport = {
      id: '01900000-0000-7000-8000-0000000a1001',
      kind: 'assets',
      mode: 'add_update',
      match_on: 'serial_number',
      dry_run: true,
      file_name: 'assets.csv',
      file_format: 'csv',
      status: 'checked',
      total: 3,
      processed: 3,
      created_count: 1,
      updated_count: 1,
      failed_count: 1,
      problems: [{ row: 4, field: 'site', code: 'site_not_found' }],
      failure: null,
      failure_detail: null,
      created_at: '2026-11-11T00:00:00Z',
      checked_at: '2026-11-11T00:00:01Z',
      finished_at: null,
      version: 4,
    };
    const fake = assetsApi({
      routes: {
        'POST /api/v1/assets/imports': {
          status: 201,
          body: { ...checked, status: 'queued', version: 1 },
        },
        'GET /api/v1/assets/imports': { body: [] },
        [`GET /api/v1/assets/imports/${checked.id}`]: { body: checked },
        [`POST /api/v1/assets/imports/${checked.id}/run`]: {
          body: { ...checked, dry_run: false, status: 'queued', version: 5 },
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('assets-import-open'));
    const input = await screen.findByTestId('asset-import-file');
    fireEvent.change(input, { target: { files: [new File(['1'], 'assets.csv')] } });
    fireEvent.click(screen.getByTestId('asset-import-check'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/imports')).toHaveLength(1);
    });
    const upload = fake.find('POST', '/api/v1/assets/imports')[0];
    expect(upload?.url.searchParams.get('dry_run')).toBe('true');
    expect(upload?.url.searchParams.get('kind')).toBe('assets');
    expect(upload?.url.searchParams.get('match_on')).toBe('serial_number');
    expect((await screen.findByTestId('asset-import-would')).textContent).toBe(
      'Would add 1 and update 1. Rows with problems: 1.',
    );
    const problems = screen.getByTestId('asset-import-problems');
    expect(problems.textContent).toContain('Site');
    expect(problems.textContent).not.toContain('site_not_found');
    fireEvent.click(screen.getByTestId('asset-import-run'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/assets/imports/${checked.id}/run`)).toHaveLength(1);
    });
    expect(
      fake.find('POST', `/api/v1/assets/imports/${checked.id}/run`)[0]?.headers.get('If-Match'),
    ).toBe('"4"');
  });

  it('the export sends the list as shown, with money only when the person may see it', async () => {
    window.history.pushState({}, '', '/assets');
    const fake = assetsApi({
      permissions: ['assets.view', 'assets.manage', 'reports.export'],
      routes: { 'POST /api/v1/reports/exports': { status: 202, body: {} } },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('assets-export'));
    expect((await screen.findByTestId('assets-export-money')).textContent).toBe(
      'Costs are left out.',
    );
    fireEvent.click(screen.getByTestId('assets-export-start'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/reports/exports')).toHaveLength(1);
    });
    const body = fake.find('POST', '/api/v1/reports/exports')[0]?.body as {
      definition: { entity: string; columns: string[] };
    };
    expect(body.definition.entity).toBe('asset');
    expect(body.definition.columns.some((c) => MONEY_COLUMNS.includes(c))).toBe(false);
  });

  it('a built-in view that is no filter is not exported, and says why', async () => {
    window.history.pushState({}, '', '/assets?view=loanable');
    const fake = assetsApi();
    restore = fake.restore;
    render(<App />);
    const button = await screen.findByTestId('assets-export');
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  it('the import wizard and the bulk dialog read right to left in Arabic and Urdu', async () => {
    for (const locale of ['ar', 'ur'] as const) {
      window.history.pushState({}, '', '/assets');
      const fake = assetsApi({ locale });
      restore = fake.restore;
      const { unmount } = render(<App />);
      fireEvent.click(await screen.findByTestId('assets-import-open'));
      const drawer = await screen.findByTestId('asset-import-drawer');
      await waitFor(() => {
        expect(document.documentElement.getAttribute('dir')).toBe('rtl');
      });
      expect(drawer.textContent).toContain(locale === 'ar' ? 'استيراد من ملف' : 'فائل سے درآمد');
      expect(drawer.textContent).not.toContain('asset_import');
      unmount();
      fake.restore();
    }
  });
});
