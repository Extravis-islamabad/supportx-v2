import { fireEvent, render, screen, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { fakePermissions, problem } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-053 S5c (REQ-CMDB-019): a CI's linked work items on its Associations tab. Per type, open of
// total (only what the reader may see, D-158); a type opens its list, by label, never a code.
// Until work items offer the links the API says "not available" and there is no tab at all.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const CI = 'a0000000-0000-7000-8000-000000000003';
const INCIDENT = 'a0000000-0000-7000-8000-000000000051';
const now = new Date().toISOString();

const ci = {
  id: CI,
  display_id: 'CI-1',
  name: 'Mail server',
  type_id: 'a0000000-0000-7000-8000-000000000001',
  state_id: 'a0000000-0000-7000-8000-000000000002',
  site_id: null,
  owner_user_id: null,
  owner_group_id: null,
  managed_by_group_id: null,
  business_impact: null,
  criticality: null,
  asset_id: null,
  source: 'manual',
  updated_at: now,
  version: 3,
  description: null,
  created_at: now,
  created_by: null,
  updated_by: null,
  deleted_at: null,
  history_count: 0,
  can_edit: true,
  can_delete: true,
  custom: {},
  masked_fields: [],
  read_only_fields: [],
  names: {},
};

function api(linked: 'available' | 'not_available') {
  const fake = consoleApi({
    me: fakeSession({}, { permissions: fakePermissions('technician') }),
    routes: {
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/cmdb/ci-states': { body: { items: [] } },
      'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
      [`GET /api/v1/cmdb/cis/${CI}`]: { body: ci, headers: { ETag: '"3"' } },
      [`GET /api/v1/cmdb/cis/${CI}/history`]: {
        body: { items: [], has_more: false, next_cursor: null },
      },
      [`GET /api/v1/cmdb/cis/${CI}/linked`]:
        linked === 'available'
          ? {
              body: {
                kinds: [
                  { kind: 'incident', open: 2, total: 3 },
                  { kind: 'service_request', open: 0, total: 0 },
                  { kind: 'problem', open: 0, total: 0 },
                  { kind: 'change', open: 0, total: 0 },
                  { kind: 'release', open: 0, total: 0 },
                ],
              },
            }
          : { status: 404, body: problem(404, 'linked_records_not_available') },
      [`GET /api/v1/cmdb/cis/${CI}/linked/incident`]: {
        body: {
          items: [
            {
              id: INCIDENT,
              kind: 'incident',
              display_id: 'INC-7',
              subject: 'Mail is slow',
              status: 'in_progress',
              open: true,
              updated_at: now,
            },
          ],
          next_cursor: null,
        },
      },
    },
  });
  restore = fake.restore;
  return fake;
}

function Shown() {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>
  );
}

describe("CMDB › a CI's Associations tab", () => {
  it('counts open of total per type you may see, and lists a type by label', async () => {
    setDefaultClientFactory(inertClientFactory);
    api('available');
    window.history.pushState({}, '', `/cmdb/${CI}?tab=associations`);
    render(<Shown />);
    const tab = await screen.findByTestId('ci-associations');
    const incidents = await within(tab).findByTestId('ci-associations-incident');
    expect(incidents.textContent).toContain('2 open of 3');
    // Types with nothing you may see are no news: not listed at all.
    expect(within(tab).queryByTestId('ci-associations-change')).toBeNull();
    fireEvent.click(incidents);
    const drawer = await screen.findByTestId('ci-associations-drawer');
    const link = await within(drawer).findByRole('link', { name: /INC-7/ });
    expect(link.getAttribute('href')).toBe(`/incidents/${INCIDENT}`);
    expect(drawer.textContent).toContain('Open');
    expect(drawer.textContent).not.toMatch(/in_progress|incident\b|service_request/);
  });

  it('has no Associations tab while work items do not offer the links', async () => {
    setDefaultClientFactory(inertClientFactory);
    api('not_available');
    window.history.pushState({}, '', `/cmdb/${CI}`);
    render(<Shown />);
    const tabs = await screen.findByTestId('ci-tabs');
    await within(tabs).findByText('Details');
    expect(within(tabs).queryByText('Associations')).toBeNull();
  });
});
