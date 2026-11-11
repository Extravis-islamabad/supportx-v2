import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type {
  AssetAudit,
  AssetAuditItem,
  AssetLabelJob,
  AssetOverdueRule,
  AssetRecord,
  AssetScan,
} from '@supportx/api-client';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-049b s3: asset audits (REQ-AST-042, 043), labels (039), scans (054), the overdue rule (056).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const SITE_A = '01900000-0000-7000-8000-00000000aa01';
const SITE_B = '01900000-0000-7000-8000-00000000aa02';
const ME = '01900000-0000-7000-8000-000000000101';
const audit: AssetAudit = {
  id: '01900000-0000-7000-8000-00000000ad01',
  display_id: 'AUD-3',
  name: 'Q4 count',
  kind: 'technician',
  description: null,
  site_ids: [SITE_A],
  product_type_ids: [],
  group_ids: [],
  planned_start: '2026-11-10',
  planned_end: '2026-11-20',
  state: 'running',
  started_at: '2026-11-10T08:00:00Z',
  closed_at: null,
  auditors: [{ id: ME, name: 'Tariq Technician' }],
  progress: { expected: 2, marked: 1, found: 0, unexpected: 0, discrepancies: 1 },
  may_manage: true,
  may_mark: true,
  created_at: '2026-11-09T08:00:00Z',
  updated_at: '2026-11-10T08:00:00Z',
  version: 2,
};
const wrong: AssetAuditItem = {
  id: 'item-1',
  asset_id: '01900000-0000-7000-8000-00000000f501',
  tag: 'AST-41',
  name: 'Laptop L1',
  kind: 'expected',
  expected_site_id: SITE_A,
  site_id: SITE_A,
  state_id: '01900000-0000-7000-8000-00000000a001',
  result: 'wrong_place',
  method: 'scanned',
  marked_by: { id: ME, name: 'Tariq Technician' },
  marked_at: '2026-11-10T09:00:00Z',
  seen_site_id: SITE_B,
  note: null,
  dispute_comment: null,
  fix: null,
  fixed_at: null,
  discrepancy: true,
  version: 2,
};
const open: AssetAuditItem = {
  ...wrong,
  id: 'item-2',
  asset_id: '01900000-0000-7000-8000-00000000f502',
  tag: 'AST-42',
  name: 'Laptop L2',
  result: null,
  method: null,
  marked_by: null,
  marked_at: null,
  seen_site_id: null,
  discrepancy: false,
  version: 1,
};
const sites = [
  { id: SITE_A, name: 'North office' },
  { id: SITE_B, name: 'South office' },
];

function api(roles: string[], routes = {}) {
  return consoleApi({
    me: fakeSession({ roles, id: ME }),
    routes: {
      'GET /api/v1/assets/audits': { body: [audit] },
      [`GET /api/v1/assets/audits/${audit.id}`]: { body: audit, headers: { ETag: '"2"' } },
      [`GET /api/v1/assets/audits/${audit.id}/items`]: (request: Request) => ({
        body:
          new URL(request.url).searchParams.get('discrepancies') === 'true'
            ? [wrong]
            : [wrong, open],
      }),
      'GET /api/v1/organization/sites': { body: sites },
      'GET /api/v1/assets/states': { body: [] },
      'GET /api/v1/assets/product-types': { body: [] },
      'GET /api/v1/assets/groups': { body: [] },
      ...routes,
    },
  });
}

describe('asset audits (REQ-AST-042, 043)', () => {
  it('lists the audits with their state and progress, live', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/assets/audits');
    let rows = [audit];
    const fake = api(['tenant_admin'], { 'GET /api/v1/assets/audits': () => ({ body: rows }) });
    restore = fake.restore;
    render(<App />);
    const row = await screen.findByTestId(`audit-row-${audit.id}`);
    expect(row.textContent).toBe('AUD-3');
    const table = screen.getByTestId('asset-audits');
    expect(within(table).getByText('Running')).toBeTruthy(); // the state's label, never the code
    expect(within(table).getByText('0 of 2 found')).toBeTruthy();
    expect(screen.getByTestId('audit-plan-open')).toBeTruthy();
    rows = [{ ...audit, progress: { ...audit.progress, found: 1, marked: 2 } }];
    act(() => {
      realtime.publish(':broadcast', { type: 'assets.audits_changed', ids: [audit.id] });
    });
    expect(await within(table).findByText('1 of 2 found')).toBeTruthy();
  });

  it('plans an audit with an Idempotency-Key', async () => {
    window.history.pushState({}, '', '/assets/audits');
    const fake = api(['tenant_admin'], {
      'POST /api/v1/assets/audits': { status: 201, body: { ...audit, state: 'draft' } },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('audit-plan-open'));
    const drawer = await screen.findByTestId('audit-plan-drawer');
    fireEvent.change(within(drawer).getByTestId('audit-name'), { target: { value: 'Q4 count' } });
    fireEvent.click(within(drawer).getByTestId('edit-ok'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/audits')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/assets/audits');
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(sent?.body).toMatchObject({ name: 'Q4 count', kind: 'technician', site_ids: [] });
  });

  it('an auditor marks by scanning and sees the progress move live (043 AC3)', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', `/assets/audits/${audit.id}`);
    let shown = audit;
    const fake = api(['technician'], {
      [`GET /api/v1/assets/audits/${audit.id}`]: () => ({ body: shown }),
      [`POST /api/v1/assets/audits/${audit.id}/scans`]: {
        status: 201,
        body: { ...open, result: 'found', method: 'scanned' },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('audit-heading')).textContent).toBe('Q4 count');
    const items = await screen.findByTestId('audit-items');
    expect(within(items).getByText('Wrong place')).toBeTruthy();
    expect(within(items).getByText('Seen at South office')).toBeTruthy();
    fireEvent.change(screen.getByTestId('audit-scan-code'), { target: { value: 'AST-42' } });
    fireEvent.click(screen.getByTestId('audit-scan-submit'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/assets/audits/${audit.id}/scans`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/assets/audits/${audit.id}/scans`);
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(sent?.body).toMatchObject({ code: 'AST-42', seen_site_id: SITE_A });
    expect((await screen.findByTestId('audit-scan-said')).textContent).toBe('AST-42: Found');
    shown = { ...audit, progress: { ...audit.progress, found: 1, marked: 2 } };
    act(() => {
      realtime.publish(`:asset_audit:${audit.id}`, {
        type: 'assets.audit_changed',
        ids: [audit.id, 'item-2'],
        fields: ['items', 'progress'],
      });
    });
    expect(await screen.findByText('1 of 2 found')).toBeTruthy();
  });

  it('a manager settles discrepancies in bulk: move to site B (043 AC2)', async () => {
    window.history.pushState({}, '', `/assets/audits/${audit.id}`);
    const fake = api(['tenant_admin'], {
      [`POST /api/v1/assets/audits/${audit.id}/fixes`]: {
        body: { outcomes: [{ item_id: 'item-1', applied: true, code: null }], applied: 1 },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Discrepancies' }));
    const list = await screen.findByTestId('audit-discrepancies');
    fireEvent.click(await within(list).findByTitle('Select AST-41'));
    fireEvent.click(screen.getByTestId('audit-fix-open'));
    const dialog = await screen.findByTestId('audit-fix-dialog');
    // The site it was seen at is offered first.
    fireEvent.click(within(dialog).getByTestId('audit-fix-apply'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/assets/audits/${audit.id}/fixes`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/assets/audits/${audit.id}/fixes`);
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(sent?.body).toMatchObject({ fix: 'move_site', item_ids: ['item-1'], site_id: SITE_B });
  });

  it("a holder's dispute shows with their comment: missing because disputed", async () => {
    window.history.pushState({}, '', `/assets/audits/${audit.id}`);
    const disputed = {
      ...open,
      result: 'missing' as const,
      method: 'manual' as const,
      marked_at: '2026-11-10T10:00:00Z',
      dispute_comment: 'Returned it to IT last month',
      discrepancy: true,
    };
    const fake = api(['tenant_admin'], {
      [`GET /api/v1/assets/audits/${audit.id}/items`]: { body: [disputed] },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('audit-dispute-item-2')).textContent).toBe(
      'Disputed by the holder: Returned it to IT last month',
    );
  });

  it('a closed audit is read-only: no marking, no scanning, no fixes', async () => {
    window.history.pushState({}, '', `/assets/audits/${audit.id}`);
    const closed = {
      ...audit,
      state: 'closed' as const,
      may_mark: false,
      closed_at: '2026-11-20T08:00:00Z',
    };
    const fake = api(['tenant_admin'], {
      [`GET /api/v1/assets/audits/${audit.id}`]: { body: closed },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByText('This audit is closed: it can no longer change.')).toBeTruthy();
    await screen.findByTestId('audit-items');
    expect(screen.queryByTestId('audit-scan')).toBeNull();
    expect(screen.queryByTestId('audit-mark-found-item-2')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: 'Discrepancies' }));
    await screen.findByTestId('audit-discrepancies');
    expect(screen.queryByTestId('audit-fix-bar')).toBeNull();
  });
});

const asset: AssetRecord = {
  id: wrong.asset_id,
  name: 'Laptop L1',
  loanable: false,
  product_id: '01900000-0000-7000-8000-00000000e001',
  product_type_id: '01900000-0000-7000-8000-00000000c001',
  state_id: wrong.state_id,
  tag: 'AST-41',
  serial_number: null,
  discovered_serial: null,
  barcode: null,
  vendor_id: null,
  site_id: SITE_B,
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
  cost_centre: null,
  gl_code: null,
  custom: {},
  created_at: '2025-11-01T00:00:00Z',
  updated_at: '2026-11-05T00:00:00Z',
  version: 3,
};
const job: AssetLabelJob = {
  id: 'job-1',
  target: 'asset',
  layout: 'laptop',
  symbology: 'qr',
  item_count: 1,
  done: 0,
  status: 'running',
  problem: null,
  pages: null,
  size_bytes: null,
  reprint_of: null,
  created_at: '2026-11-11T08:00:00Z',
  finished_at: null,
  expires_at: null,
};
const scans: AssetScan[] = [
  {
    id: 'scan-2',
    scanned_at: '2026-11-10T08:00:00Z',
    source: 'probe',
    scan_type: null,
    result: 'failed',
    failure_reason: 'credentials_refused',
    changes: [],
  },
  {
    id: 'scan-1',
    scanned_at: '2026-11-09T08:00:00Z',
    source: 'agent',
    scan_type: 'hardware',
    result: 'ok',
    failure_reason: null,
    changes: [
      {
        kind: 'hardware_added',
        category: 'disk',
        name: 'NVMe SSD',
        model: 'MZ-V8V1T0',
        capacity: '1 TB',
        serial: null,
        version: null,
        publisher: null,
      },
    ],
  },
];

function assetApi(roles: string[], routes = {}) {
  return consoleApi({
    me: fakeSession({ roles, id: ME }),
    routes: {
      [`GET /api/v1/assets/${asset.id}`]: { body: asset, headers: { ETag: '"3"' } },
      [`GET /api/v1/assets/${asset.id}/history`]: {
        body: {
          items: [
            {
              version: 3,
              kind: 'updated',
              actor_id: ME,
              actor_name: 'Aisha Admin',
              source: 'ui',
              reason: null,
              occurred_at: '2026-11-10T10:00:00Z',
              changes: [{ field: 'site_id', old: SITE_A, new: SITE_B }],
              origin: {
                kind: 'asset_audit',
                audit_id: audit.id,
                display_id: 'AUD-3',
                name: 'Q4 count',
              },
            },
          ],
          next_cursor: null,
        },
      },
      [`GET /api/v1/assets/${asset.id}/notes`]: { body: [] },
      [`GET /api/v1/assets/${asset.id}/scans`]: { body: { items: scans, next_cursor: null } },
      'GET /api/v1/assets/labels/prints': { body: [] },
      [`GET /api/v1/files/records/asset/${asset.id}`]: { body: [] },
      'GET /api/v1/assets/states': { body: [] },
      'GET /api/v1/assets/product-types': { body: [] },
      ...routes,
    },
  });
}

describe('labels, scans and history origin on the asset page', () => {
  it('prints a label for the asset and offers the PDF once it is ready (039)', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', `/assets/${asset.id}`);
    let jobs = [job];
    const fake = assetApi(['technician'], {
      'POST /api/v1/assets/labels': { status: 202, body: job },
      'GET /api/v1/assets/labels/jobs': () => ({ body: jobs }),
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('asset-tabs');
    // For someone who manages the asset it sits under "More actions".
    fireEvent.click(screen.getByTestId('asset-actions-more'));
    fireEvent.click(await screen.findByTestId('asset-labels-open-menu'));
    const dialog = await screen.findByTestId('labels-dialog');
    fireEvent.click(within(dialog).getByTestId('edit-ok'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/assets/labels')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/assets/labels');
    expect(sent?.headers.get('Idempotency-Key')).toBeTruthy();
    expect(sent?.body).toMatchObject({ asset_ids: [asset.id], layout: 'laptop', symbology: 'qr' });
    expect(await within(dialog).findByText('Preparing')).toBeTruthy();
    jobs = [{ ...job, status: 'ready', done: 1, pages: 1, size_bytes: 900 }];
    act(() => {
      realtime.publish(`:user:${ME}`, { type: 'assets.labels_changed', ids: ['job-1'] });
    });
    const link = await within(dialog).findByTestId('label-job-download-job-1');
    expect(link.getAttribute('href')).toBe('/api/v1/assets/labels/jobs/job-1/file');
  });

  it('the Scans tab lists what changed and why a scan failed (054)', async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=scans`);
    const fake = assetApi(['technician']);
    restore = fake.restore;
    render(<App />);
    const table = await screen.findByTestId('asset-scans');
    expect((await within(table).findByTestId('scan-reason-scan-2')).textContent).toBe(
      'Credentials were refused',
    );
    expect(within(table).getByTestId('scan-changes-scan-1').textContent).toBe(
      'Hardware added · Disk: NVMe SSD (MZ-V8V1T0, 1 TB)',
    );
    expect(within(table).getByText('Probe')).toBeTruthy();
  });

  it("the overdue rule's move shows its labelled reason, with the days", async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=history`);
    const fake = assetApi(['tenant_admin'], {
      [`GET /api/v1/assets/${asset.id}/history`]: {
        body: {
          items: [
            {
              version: 4,
              kind: 'updated',
              actor_id: null,
              actor_name: null,
              source: 'rule',
              reason: null,
              occurred_at: '2026-11-11T10:00:00Z',
              changes: [{ field: 'state_id', old: 'a', new: 'b' }],
              origin: {
                kind: 'asset_overdue_rule',
                audit_id: null,
                display_id: null,
                name: null,
                reason_code: 'overdue_scan_rule',
                reason_params: { days: 60 },
              },
            },
          ],
          next_cursor: null,
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('asset-history-origin')).textContent).toBe(
      'Overdue scan rule: not scanned for 60 days',
    );
  });

  it("a fix's history entry names the audit it came from", async () => {
    window.history.pushState({}, '', `/assets/${asset.id}?tab=history`);
    const fake = assetApi(['tenant_admin']);
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('asset-history-origin')).textContent).toBe(
      'From audit AUD-3: Q4 count',
    );
  });
});

const rule: AssetOverdueRule = {
  enabled: false,
  days: 60,
  product_type_ids: [],
  action: 'move_state',
  state_id: null,
  version: 1,
};

describe('the overdue-scan rule (056)', () => {
  it('is off by default, shows its effect before it can be saved, and saves with If-Match', async () => {
    window.history.pushState({}, '', '/admin/assets?tab=settings');
    const fake = consoleApi({
      me: fakeSession({ roles: ['tenant_admin'] }),
      routes: {
        'GET /api/v1/assets/settings': {
          body: {
            tag_pattern: 'AST-{n}',
            age_basis: 'acquisition_date',
            cost_includes_tax: true,
            copy_limit: 50,
            site_follows_owner: false,
            portal_own_assets_only: true,
            email_include_assets: false,
            warranty_notice_days: 30,
            scan_retention_months: 6,
            portal_booking: false,
            version: 1,
          },
        },
        'GET /api/v1/assets/states': { body: [] },
        'GET /api/v1/assets/life-cycles': { body: [] },
        'GET /api/v1/assets/product-types': { body: [] },
        'GET /api/v1/assets/stock-rules': { body: [] },
        'GET /api/v1/assets/overdue-rule': { body: rule },
        'GET /api/v1/assets/overdue-rule/runs': { body: [] },
        'GET /api/v1/assets/overdue-rule/states': { body: { state_ids: [] } },
        'POST /api/v1/assets/overdue-rule/preview': { body: { count: 3 } },
        'PATCH /api/v1/assets/overdue-rule': {
          body: { ...rule, action: 'trash', enabled: true, version: 2 },
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    const card = await screen.findByTestId('asset-overdue-rule');
    const enabled = within(card).getByTestId('asset-overdue-enabled');
    expect(enabled.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(enabled);
    expect(within(card).getByTestId('asset-overdue-save').hasAttribute('disabled')).toBe(true);
    // A move needs its state first: the preview says why it waits.
    expect(within(card).getByTestId('asset-overdue-check').hasAttribute('disabled')).toBe(true);
    // The strongest action is the trash (restorable), never a delete.
    const action = within(card).getByTestId('asset-overdue-action');
    fireEvent.mouseDown(action.querySelector('.ant-select-selector') ?? action);
    fireEvent.click(await screen.findByTitle('Move to the trash (can be restored)'));
    fireEvent.click(within(card).getByTestId('asset-overdue-check'));
    expect((await within(card).findByTestId('asset-overdue-preview')).textContent).toBe(
      'Saved like this, it would change 3 assets now.',
    );
    const [previewed] = fake.find('POST', '/api/v1/assets/overdue-rule/preview');
    expect(previewed?.body).toMatchObject({ enabled: true, action: 'trash', days: 60 });
    fireEvent.click(within(card).getByTestId('asset-overdue-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/assets/overdue-rule')).toHaveLength(1);
    });
    expect(fake.find('PATCH', '/api/v1/assets/overdue-rule')[0]?.headers.get('If-Match')).toBe(
      '"1"',
    );
  });
});
