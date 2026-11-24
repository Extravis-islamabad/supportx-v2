import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { fakePermissions, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../App';
import { openMoreActions } from '../../test/actions';
import { consoleApi } from '../../test/api';

// WP-053 S4b (REQ-CMDB-017): a merged CI's ID opens its survivor; the merge drawer names every
// value through what the reader may see (a state by its name, a site by the server's name for
// it, never an ID), and lists only the fields the server offers.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const TYPE = 'a0000000-0000-7000-8000-000000000101';
const STATE = 'a0000000-0000-7000-8000-000000000102';
const CI = 'a0000000-0000-7000-8000-000000000103';
const DUPE = 'a0000000-0000-7000-8000-000000000104';
const OLD = 'a0000000-0000-7000-8000-000000000105';
const SITE = 'a0000000-0000-7000-8000-000000000106';
const now = new Date().toISOString();
const named = (label: string) => ({ label, restricted: false, gone: false });

function record(id: string, displayId: string, name: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    display_id: displayId,
    name,
    type_id: TYPE,
    state_id: STATE,
    site_id: null,
    owner_user_id: null,
    owner_group_id: null,
    managed_by_group_id: null,
    business_impact: null,
    criticality: null,
    asset_id: null,
    source: 'manual',
    updated_at: now,
    version: 2,
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
    ...extra,
  };
}

const kept = record(CI, 'CI-10', 'Payroll app');
const dupe = record(DUPE, 'CI-11', 'Payroll app (old)', {
  site_id: SITE,
  names: { [SITE]: named('Islamabad HQ') },
});

// An administrator who also holds cmdb.manage (the merge's right).
const MANAGER = fakeSession(
  { roles: ['tenant_admin'] },
  {
    permissions: [
      ...fakePermissions('tenant_admin'),
      { key: 'cmdb.manage', scope: 'all', scopes: ['all'], conditional: false },
    ],
  },
);

function api() {
  const fake = consoleApi({
    me: MANAGER,
    routes: {
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/cmdb/ci-states': {
        body: {
          items: [
            {
              id: STATE,
              api_name: 'active',
              built_in: true,
              names: {},
              category: 'active',
              position: 0,
              ci_count: 0,
              version: 1,
            },
          ],
        },
      },
      'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
      [`GET /api/v1/cmdb/cis/${CI}`]: { body: kept, headers: { ETag: '"2"' } },
      [`GET /api/v1/cmdb/cis/${CI}/history`]: {
        body: { items: [], has_more: false, next_cursor: null },
      },
      [`GET /api/v1/cmdb/cis/${CI}/subscribers`]: {
        body: { business_service: false, people: 0, items: [] },
      },
      [`GET /api/v1/cmdb/cis/${OLD}`]: {
        status: 404,
        body: {
          code: 'cmdb_ci_merged',
          message_key: 'errors.cmdb_ci_merged',
          params: { survivor_id: CI },
          errors: [],
        },
      },
      'GET /api/v1/cmdb/cis/picker': {
        body: { items: [{ ...dupe, history_count: undefined }] },
      },
      'GET /api/v1/cmdb/merges/preview': {
        body: {
          survivor: kept,
          merged: dupe,
          swapped: false,
          fields: [
            {
              field: 'name',
              survivor: 'Payroll app',
              merged: 'Payroll app (old)',
              side: 'survivor',
            },
            { field: 'site_id', survivor: null, merged: SITE, side: 'merged' },
            { field: 'state_id', survivor: STATE, merged: STATE, side: 'survivor' },
          ],
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

describe('CMDB › merging duplicates', () => {
  it('opens the survivor from a merged CI’s ID', async () => {
    setDefaultClientFactory(inertClientFactory);
    api();
    window.history.pushState({}, '', `/cmdb/${OLD}`);
    render(<Shown />);
    await screen.findByTestId('ci-panel');
    await waitFor(() => {
      expect(window.location.pathname).toBe(`/cmdb/${CI}`);
    });
    expect(screen.getAllByText('Payroll app').length).toBeGreaterThan(0);
  });

  it('names each value in the merge drawer, never by its ID', async () => {
    setDefaultClientFactory(inertClientFactory);
    api();
    window.history.pushState({}, '', `/cmdb/${CI}`);
    render(<Shown />);
    await screen.findByTestId('ci-panel');
    const menu = await openMoreActions('ci-actions');
    fireEvent.click(within(menu).getByTestId('ci-merge'));
    const drawer = await screen.findByTestId('ci-merge-drawer');
    const pick = within(drawer).getByTestId('ci-merge-pick');
    fireEvent.mouseDown(pick.querySelector('input') ?? pick);
    fireEvent.click(await screen.findByText('CI-11 · Payroll app (old)'));
    const fields = await within(drawer).findByTestId('ci-merge-fields');
    expect(fields.textContent).toContain('Islamabad HQ');
    expect(fields.textContent).not.toContain(SITE);
    expect(fields.textContent).not.toContain(STATE);
    expect(fields.textContent).not.toMatch(/cmdb_|_id\b/);
  });
});
