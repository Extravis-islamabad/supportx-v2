import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { fakePermissions } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-053 S5b (REQ-CMDB-020): a CI's downtimes on its record. A synced one names its source by
// label and links to that record, with no remove; a hand-recorded one can be removed by someone
// with `cmdb.record_downtime`; the counts read by state; the form waits for a start; without the
// right there is no form. Never a raw code on screen. (The Idempotency-Key and the If-Match are
// the API's own tests: tests/db/test_cmdb_downtimes.py.)

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const CI = 'a0000000-0000-7000-8000-000000000003';
const CHANGE = 'a0000000-0000-7000-8000-000000000031';
const SYNCED = 'a0000000-0000-7000-8000-000000000041';
const MANUAL = 'a0000000-0000-7000-8000-000000000042';
const now = new Date().toISOString();
const later = new Date(Date.now() + 3_600_000).toISOString();

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

const downtimes = {
  items: [
    {
      id: SYNCED,
      ci_id: CI,
      source: 'change',
      source_work_item_id: CHANGE,
      phase: 'planned',
      kind: 'full_outage',
      starts_at: later,
      ends_at: later,
      description: null,
      state: 'scheduled',
      editable: false,
      version: 1,
    },
    {
      id: MANUAL,
      ci_id: CI,
      source: 'manual',
      source_work_item_id: null,
      phase: 'actual',
      kind: null,
      starts_at: now,
      ends_at: null,
      description: 'Disk swap',
      state: 'active',
      editable: true,
      version: 2,
    },
  ],
  counts: { scheduled: 1, active: 1, completed: 0 },
};

function api(mayRecord: boolean) {
  const granted = fakePermissions('technician');
  const permissions = mayRecord
    ? [
        ...granted,
        {
          key: 'cmdb.record_downtime',
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        },
      ]
    : granted;
  const fake = consoleApi({
    me: fakeSession({}, { permissions }),
    routes: {
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/cmdb/ci-states': { body: { items: [] } },
      'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
      [`GET /api/v1/cmdb/cis/${CI}`]: { body: ci, headers: { ETag: '"3"' } },
      [`GET /api/v1/cmdb/cis/${CI}/history`]: {
        body: { items: [], has_more: false, next_cursor: null },
      },
      [`GET /api/v1/cmdb/cis/${CI}/downtimes`]: { body: downtimes },
      [`POST /api/v1/cmdb/cis/${CI}/downtimes`]: { status: 201, body: downtimes.items[1] },
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

describe("CMDB › a CI's downtimes", () => {
  it('shows synced and hand-recorded ones by label, links the source, and removes only its own', async () => {
    setDefaultClientFactory(inertClientFactory);
    api(true);
    window.history.pushState({}, '', `/cmdb/${CI}?tab=downtimes`);
    render(<Shown />);
    const tab = await screen.findByTestId('ci-downtimes');
    await within(tab).findByTestId(`ci-downtime-${SYNCED}`);
    const counts = within(tab).getByTestId('ci-downtime-counts');
    expect(counts.textContent).toContain('Active: 1');
    expect(counts.textContent).toContain('Scheduled: 1');
    const synced = within(tab).getByTestId(`ci-downtime-${SYNCED}`);
    expect(synced.textContent).toContain('From a change');
    expect(synced.textContent).toContain('Scheduled');
    expect(synced.textContent).not.toContain('full_outage'); // a work item's code, never raw
    const source = within(tab).getByTestId(`ci-downtime-${SYNCED}-source`);
    expect(source.getAttribute('href')).toBe(`/changes/${CHANGE}`);
    expect(within(tab).queryByTestId(`ci-downtime-${SYNCED}-remove`)).toBeNull();
    const manual = within(tab).getByTestId(`ci-downtime-${MANUAL}`);
    expect(manual.textContent).toContain('Recorded by hand');
    expect(manual.textContent).toContain('no end yet');
    expect(manual.textContent).toContain('Disk swap');
    expect(within(tab).getByTestId(`ci-downtime-${MANUAL}-remove`)).toBeDefined();
    expect(tab.textContent).not.toMatch(/cmdb_downtime|cmdb\.downtime|scheduled\b/);
  });

  it('waits for a start before recording, and offers no form without the right', async () => {
    setDefaultClientFactory(inertClientFactory);
    const fake = api(true);
    window.history.pushState({}, '', `/cmdb/${CI}?tab=downtimes`);
    const { unmount } = render(<Shown />);
    const tab = await screen.findByTestId('ci-downtimes');
    const add = within(tab).getByTestId('ci-downtime-add');
    expect(add.hasAttribute('disabled')).toBe(true); // no start yet
    fireEvent.change(within(tab).getByTestId('ci-downtime-description'), {
      target: { value: 'Fan swap' },
    });
    expect(fake.find('POST', `/api/v1/cmdb/cis/${CI}/downtimes`)).toHaveLength(0);
    unmount();
    restore();

    api(false);
    window.history.pushState({}, '', `/cmdb/${CI}?tab=downtimes`);
    render(<Shown />);
    const readOnly = await screen.findByTestId('ci-downtimes');
    await within(readOnly).findByTestId(`ci-downtime-${MANUAL}`);
    await waitFor(() => {
      expect(within(readOnly).queryByTestId('ci-downtime-add')).toBeNull();
    });
    expect(within(readOnly).queryByTestId(`ci-downtime-${MANUAL}-remove`)).toBeNull();
  });
});
