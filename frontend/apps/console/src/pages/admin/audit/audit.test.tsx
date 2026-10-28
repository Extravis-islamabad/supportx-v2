import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { AuditEntry, AuditEntryDetail } from '@supportx/api-client';
import { fakeAuditStatus, type FakeRoute } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession, problem } from '../../../test/api';

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

function entry(overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: 'e-1',
    occurred_at: '2026-10-24T09:15:42.123456Z',
    action: 'role.updated',
    category: 'access',
    module: 'identity_access',
    outcome: 'done',
    reason_code: null,
    actor_type: 'person',
    actor_id: 'u-admin',
    actor_name: 'Amal Admin',
    on_behalf_id: null,
    object_type: 'role',
    object_id: 'r-hr',
    object_name: null,
    details: {
      grants_added: ['users.view:all'],
      grants_removed: ['roles.view:all'],
      renamed: false,
    },
    client: 'console',
    request_id: 'req-42',
    change_id: 'c-1',
    seq: 12,
    ...overrides,
  };
}

const DETAIL: AuditEntryDetail = {
  ...entry(),
  entry_hash: 'a'.repeat(64),
  prev_hash: 'b'.repeat(64),
  chain_hash: 'c'.repeat(64),
  sealed_at: '2026-10-24T09:15:43Z',
  personal: [{ subject_id: 'u-admin', ip: '10.1.2.3', user_agent: 'Firefox', reason: null }],
  names: { 'u-admin': 'Amal Admin' },
};

function page(items: AuditEntry[]) {
  return { items, has_more: false, next_cursor: null, estimated_total: null };
}

function auditRoutes(items: AuditEntry[] = [entry()], extra: Record<string, FakeRoute> = {}) {
  return api({
    me: ADMIN,
    routes: {
      'GET /api/v1/audit/entries': { body: page(items) },
      'GET /api/v1/audit/entries/e-1': { body: DETAIL },
      'GET /api/v1/audit/saved-searches': { body: [] },
      'GET /api/v1/roles': { body: [] },
      'GET /api/v1/users': { body: { items: [], has_more: false, next_cursor: null } },
      ...extra,
    },
  });
}

describe('Admin › Audit log', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/audit');
  });
  afterEach(() => {
    restore();
  });

  it('shows entries in plain words: labels, names and the chain position, never codes', async () => {
    auditRoutes([entry(), entry({ id: 'e-2', seq: null, outcome: 'refused' })]);
    render(<App />);
    const table = await screen.findByTestId('audit-table');
    expect(await within(table).findAllByText('Changed a role')).toHaveLength(2);
    expect(within(table).getAllByText('Amal Admin')).toHaveLength(2);
    expect(within(table).getByText('Sealed, position 12')).toBeDefined();
    expect(within(table).getByTestId('audit-pending-seal').textContent).toBe('Pending seal');
    expect(within(table).getByText('Refused')).toBeDefined();
    expect(within(table).queryByText('role.updated')).toBeNull();
    expect(within(table).queryByText('refused')).toBeNull();
  });

  it('filters through the URL and the API (last 30 days by default)', async () => {
    const fake = auditRoutes();
    render(<App />);
    await screen.findByTestId('audit-table');
    const first = fake.find('GET', '/api/v1/audit/entries')[0];
    expect(JSON.parse(first?.url.searchParams.get('filter') ?? '{}')).toEqual({
      field: 'occurred_at',
      op: 'last_n_days',
      value: 30,
    });
    const outcome = within(screen.getByTestId('audit-filter-outcome')).getByRole('combobox');
    fireEvent.mouseDown(outcome);
    fireEvent.click(await screen.findByTitle('Refused'));
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/audit/entries').at(-1);
      expect(last?.url.searchParams.get('outcome')).toBe('refused');
    });
  });

  it('opens an entry: grants added and removed, the IP address and the support reference', async () => {
    auditRoutes();
    render(<App />);
    fireEvent.click(await screen.findByTestId('audit-row-e-1'));
    const drawer = await screen.findByTestId('audit-entry-drawer');
    const changes = await within(drawer).findByTestId('audit-entry-changes');
    expect(within(changes).getByText(/^Added: /).textContent).toContain('All records');
    expect(within(changes).getByText(/^Removed: /)).toBeDefined();
    expect(within(drawer).getByText('10.1.2.3')).toBeDefined();
    expect(within(drawer).getByText('req-42')).toBeDefined();
    expect(within(drawer).queryByText('users.view:all')).toBeNull();
  });

  it('shows the banner while the chain has an unresolved problem', async () => {
    auditRoutes([entry()], {
      'GET /api/v1/audit/status': { body: fakeAuditStatus({ alert: 'entry_changed' }) },
    });
    render(<App />);
    const banner = await screen.findAllByTestId('audit-alert-banner');
    expect(banner[0]?.textContent).toContain('An entry was changed after it was written.');
  });

  it('the banner link reads as a link without its colour (axe link-in-text-block, WP-039 session 2)', async () => {
    auditRoutes([entry()], {
      'GET /api/v1/audit/status': { body: fakeAuditStatus({ alert: 'entry_changed' }) },
    });
    render(<App />);
    const banner = (await screen.findAllByTestId('audit-alert-banner'))[0];
    const link = banner?.querySelector<HTMLAnchorElement>('a[href="/admin/audit?tab=integrity"]');
    expect(link).toBeTruthy();
    // Inside a sentence a link needs more than colour to be seen (WCAG 1.4.1): underlined.
    expect(link?.style.textDecoration).toBe('underline');
  });

  it('is hidden from people without the audit permission', async () => {
    api({ me: fakeSession({ roles: ['technician'] }) });
    render(<App />);
    expect(await screen.findByText(/You do not have permission to do this\./)).toBeDefined();
    expect(screen.queryByTestId('audit-table')).toBeNull();
  });

  it('settings: auditors read them, admins save with If-Match, errors are explained', async () => {
    const fake = auditRoutes([entry()], {
      'GET /api/v1/audit/settings': {
        body: {
          retention_days: 1095,
          read_window_minutes: 10,
          refusal_threshold: 10,
          refusal_window_minutes: 10,
          read_categories: [
            'access_information',
            'audit_log',
            'exports',
            'secrets',
            'security_settings',
          ],
          version: 0,
          limits: {
            retention_days: [365, 3650],
            read_window_minutes: [1, 1440],
            refusal_threshold: [3, 1000],
            refusal_window_minutes: [1, 1440],
          },
        },
        headers: { ETag: '"0"' },
      },
      'PUT /api/v1/audit/settings': { status: 409, body: problem(409, 'version_conflict') },
    });
    window.history.pushState({}, '', '/admin/audit?tab=settings');
    render(<App />);
    const retention = await screen.findByTestId('audit-setting-retention_days');
    fireEvent.change(retention, { target: { value: '730' } });
    fireEvent.click(screen.getByTestId('audit-settings-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/audit/settings')).toHaveLength(1);
    });
    const sent = fake.find('PUT', '/api/v1/audit/settings')[0];
    expect(sent?.headers.get('If-Match')).toBe('"0"');
    expect((sent?.body as { retention_days: number }).retention_days).toBe(730);
    // A save someone else beat opens the shared conflict dialog (QA WP-029 BUG-05).
    expect(await screen.findByText('Someone else changed this')).toBeDefined();
    expect(screen.queryByTestId('audit-problem')).toBeNull();
    fireEvent.click(screen.getByTestId('conflict-reload'));
    // The audit log itself is always logged: its box cannot be cleared.
    const box = screen.getByTestId('audit-read-audit_log');
    const input = box.tagName === 'INPUT' ? box : box.querySelector('input');
    expect(input?.hasAttribute('disabled')).toBe(true);
  });

  it('archives: failures explained, restore asked for, restored entries in plain words', async () => {
    const archive = {
      id: 'a-1',
      range_from: '2022-03-01T00:00:00Z',
      range_to: '2022-04-01T00:00:00Z',
      status: 'ready',
      entries: 2,
      first_seq: 4,
      last_seq: 5,
      sha256: 'd'.repeat(64),
      problem: null,
      created_at: '2025-04-02T01:00:00Z',
      restore_status: 'ready',
      restore_problem: null,
      restored_until: '2025-04-09T01:00:00Z',
    };
    const fake = auditRoutes([entry()], {
      'GET /api/v1/audit/archives': {
        body: [
          {
            ...archive,
            id: 'a-2',
            range_from: '2022-04-01T00:00:00Z',
            range_to: '2022-05-01T00:00:00Z',
            status: 'failed',
            entries: 0,
            first_seq: null,
            last_seq: null,
            sha256: null,
            problem: 'storage_unavailable',
            restore_status: null,
            restored_until: null,
          },
          { ...archive, id: 'a-3', restore_status: null, restored_until: null },
          archive,
        ],
      },
      'POST /api/v1/audit/archives/a-3/restore': {
        status: 202,
        body: { ...archive, id: 'a-3', restore_status: 'running' },
      },
      'GET /api/v1/audit/archives/a-1/entries': {
        body: { items: [entry({ seq: 4 })], has_more: false, next_cursor: null },
      },
    });
    window.history.pushState({}, '', '/admin/audit?tab=archives');
    render(<App />);
    const table = await screen.findByTestId('audit-archives');
    expect(await within(table).findByText('Not archived')).toBeDefined();
    expect(within(table).getByText(/storage/i)).toBeDefined();
    expect(within(table).queryByText('storage_unavailable')).toBeNull();
    expect(within(table).getAllByText('Positions 4 to 5')).toHaveLength(2);

    fireEvent.click(within(table).getByTestId('audit-archive-restore-a-3'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/audit/archives/a-3/restore')).toHaveLength(1);
    });

    fireEvent.click(within(table).getByTestId('audit-archive-open-a-1'));
    const drawer = await screen.findByTestId('audit-restored-table');
    expect(await within(drawer).findByText('Changed a role')).toBeDefined();
    expect(within(drawer).getByText('Sealed, position 4')).toBeDefined();
  });
});
