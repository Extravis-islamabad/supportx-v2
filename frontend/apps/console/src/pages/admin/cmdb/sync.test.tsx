import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { fakePermissions, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';
import { filterOf, simpleOf } from './syncShared';

// Sync rules (WP-053 S4a): the list (template A), the editor with its preview drawer and runs
// (template B), and the run's items, where a CI or an asset the reader may not see reads
// "Not visible to you" with no ID or name (lane C's condition 5).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const RULE = '01a1fb65-0000-7000-8000-0000000000r1';
const RUN = '01a1fb65-0000-7000-8000-0000000000u1';
const SERVER_TYPE = 'a0000000-0000-7000-8000-0000000000a2';
const HIDDEN_CI = 'c0000000-0000-7000-8000-00000000hid1';
const rule = {
  id: RULE,
  name: 'Laptops become workstations',
  source_kind: 'assets',
  filter: { field: 'site_id', op: 'in', value: ['s1'] },
  target_type_id: SERVER_TYPE,
  target_state_id: null,
  field_map: { name: 'name', description: 'location' },
  enabled: true,
  updated_at: '2026-11-21T09:00:00Z',
  version: 3,
};
const run = {
  id: RUN,
  rule_id: RULE,
  trigger: 'schedule',
  status: 'succeeded',
  incremental: false,
  started_at: '2026-11-21T09:00:00Z',
  ended_at: '2026-11-21T09:00:05Z',
  created_count: 1,
  updated_count: 0,
  kept_count: 1,
  unchanged_count: 0,
  failed_count: 0,
  failure: null,
  created_at: '2026-11-21T09:00:00Z',
  version: 3,
};
const ADMIN = fakeSession(
  { roles: ['tenant_admin'] },
  {
    permissions: [
      ...fakePermissions('tenant_admin'),
      { key: 'cmdb.configure', scope: 'all', scopes: ['all'], conditional: false },
    ],
  },
);
const FIELDS = {
  asset_fields: [
    { key: 'name', kind: 'text' },
    { key: 'location', kind: 'text' },
    { key: 'site_id', kind: 'site' },
  ],
  ci_attributes: [
    { key: 'name', kind: 'text' },
    { key: 'description', kind: 'text' },
    { key: 'site_id', kind: 'site' },
  ],
  filter_fields: ['product_type_id', 'site_id', 'state_id'],
};

function api(extra: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/cmdb/ci-types': {
        body: {
          items: [
            {
              id: SERVER_TYPE,
              parent_id: null,
              api_name: 'server',
              built_in: true,
              names: {},
              icon: null,
              ci_count: 0,
              child_count: 0,
              version: 1,
            },
          ],
        },
      },
      'GET /api/v1/cmdb/ci-states': { body: { items: [] } },
      'GET /api/v1/cmdb/sync-rules': { body: { items: [rule] } },
      [`GET /api/v1/cmdb/sync-rules/${RULE}`]: { body: rule, headers: { ETag: '"3"' } },
      'GET /api/v1/cmdb/sync-rules/fields': { body: FIELDS },
      [`GET /api/v1/cmdb/sync-rules/${RULE}/runs`]: { body: { items: [run] } },
      [`GET /api/v1/cmdb/sync-runs/${RUN}`]: {
        body: {
          ...run,
          items: [
            {
              outcome: 'kept',
              asset_id: null,
              asset_label: null,
              asset_restricted: true,
              ci_id: null,
              ci_label: null,
              ci_restricted: true,
              kept: [],
              code: null,
            },
          ],
        },
      },
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/assets/product-types': { body: [] },
      'GET /api/v1/assets/states': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      ...(extra as Record<string, never>),
    },
  });
  restore = fake.restore;
  return fake;
}

function open(path: string) {
  window.history.pushState({}, '', path);
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>,
  );
}

describe('the sync filter', () => {
  it('builds the asset list’s DSL and reads it back', () => {
    const simple = { productTypeIds: ['p1'], siteIds: ['s1', 's2'], stateIds: [] };
    expect(filterOf(simple)).toEqual({
      and: [
        { field: 'product_type_id', op: 'in', value: ['p1'] },
        { field: 'site_id', op: 'in', value: ['s1', 's2'] },
      ],
    });
    expect(simpleOf(filterOf(simple))).toEqual(simple);
    expect(filterOf({ productTypeIds: [], siteIds: [], stateIds: [] })).toBeNull();
    // A shape the editor cannot show (made through the API) is kept as it is.
    expect(simpleOf({ field: 'name', op: 'contains', value: 'x' })).toBeNull();
  });
});

describe('Admin › CMDB › sync rules', () => {
  it('lists the rules with their state', async () => {
    api();
    open('/admin/cmdb/sync-rules');
    const link = await screen.findByTestId(`cmdb-sync-link-${RULE}`);
    expect(link.textContent).toBe('Laptops become workstations');
    expect(screen.getByTestId('cmdb-sync-table').textContent).toContain('On');
  });

  it('previews an unsaved rule in a drawer, then saves it with an Idempotency-Key', async () => {
    const fake = api({
      'POST /api/v1/cmdb/sync-rules/preview': {
        body: {
          total: 40,
          complete: true,
          counts: { created: 40, updated: 0, kept: 0, unchanged: 0, failed: 0 },
          items: [],
        },
      },
      'POST /api/v1/cmdb/sync-rules': { status: 201, body: { ...rule, version: 1 } },
    });
    open(`/admin/cmdb/sync-rules/${RULE}`);
    const name = await screen.findByTestId('cmdb-sync-name');
    await waitFor(() => {
      expect((name as HTMLInputElement).value).toBe('Laptops become workstations');
    });
    fireEvent.click(screen.getByTestId('cmdb-sync-preview'));
    const drawer = await screen.findByTestId('cmdb-sync-preview-body');
    expect(drawer.textContent).toContain('Matching assets: 40');
    const sent = fake.find('POST', '/api/v1/cmdb/sync-rules/preview')[0]?.body;
    expect(sent).toMatchObject({
      name: 'Laptops become workstations',
      field_map: { name: 'name', description: 'location' },
      filter: { field: 'site_id', op: 'in', value: ['s1'] },
    });
    // Nothing saved by a preview.
    expect(fake.find('POST', '/api/v1/cmdb/sync-rules')).toHaveLength(0);
  });

  it('shows a run’s items without naming what the reader may not see', async () => {
    api();
    open(`/admin/cmdb/sync-rules/${RULE}`);
    fireEvent.click(await screen.findByTestId(`cmdb-sync-run-${RUN}`));
    const body = await screen.findByTestId('cmdb-sync-run-body');
    await waitFor(() => {
      expect(within(body).getAllByText('Not visible to you')).toHaveLength(2);
    });
    expect(body.textContent).not.toContain(HIDDEN_CI);
  });

  it('says the totals are hidden when the server withholds them', async () => {
    const hidden = {
      ...run,
      created_count: null,
      updated_count: null,
      kept_count: null,
      unchanged_count: null,
      failed_count: null,
    };
    api({
      [`GET /api/v1/cmdb/sync-rules/${RULE}/runs`]: { body: { items: [hidden] } },
      [`GET /api/v1/cmdb/sync-runs/${RUN}`]: { body: { ...hidden, items: [] } },
    });
    open(`/admin/cmdb/sync-rules/${RULE}`);
    const runs = await screen.findByTestId('cmdb-sync-runs');
    await waitFor(() => {
      expect(within(runs).queryByText(/Created/)).toBeNull();
    });
    fireEvent.click(await screen.findByTestId(`cmdb-sync-run-${RUN}`));
    expect((await screen.findByTestId('cmdb-sync-totals-hidden')).textContent).toContain(
      'Totals hidden: some items are outside your access.',
    );
  });
});
