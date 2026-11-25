import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../App';
import { openMoreActions } from '../../test/actions';
import { consoleApi } from '../../test/api';
import { ciRaisePath } from './raise';

// WP-053 S5c (REQ-CMDB-019 AC1): raise an incident, request or change from a CI. Each entry shows
// only with its create right; the form opens with the template (a request's item) and `ci=`,
// which lane A's create forms link (#638). Every word is a label, in en and ar.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const CI = 'a0000000-0000-7000-8000-000000000003';
const TEMPLATE = 'a0000000-0000-7000-8000-000000000071';
const ITEM = 'a0000000-0000-7000-8000-000000000072';
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
  can_edit: false,
  can_delete: false,
  custom: {},
  masked_fields: [],
  read_only_fields: [],
  names: {},
};

function grant(key: string) {
  return { key, scope: 'all' as const, scopes: ['all' as const], conditional: false };
}

function api(rights: string[], locale: 'en' | 'ar' = 'en') {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['technician'], locale },
      { permissions: ['cmdb.view', ...rights].map(grant) },
    ),
    routes: {
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/cmdb/ci-states': { body: { items: [] } },
      'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
      [`GET /api/v1/cmdb/cis/${CI}`]: { body: ci, headers: { ETag: '"3"' } },
      [`GET /api/v1/cmdb/cis/${CI}/history`]: {
        body: { items: [], has_more: false, next_cursor: null },
      },
      'GET /api/v1/incidents/templates': {
        body: [
          {
            id: TEMPLATE,
            code: null,
            labels: { en: 'Server down', ar: 'الخادم متوقف' },
            disabled: false,
            is_default: true,
          },
        ],
      },
      'GET /api/v1/catalog/items': {
        body: [
          {
            id: ITEM,
            names: { en: 'Disk space', ar: 'مساحة القرص' },
            status: 'published',
            kind: 'service',
          },
        ],
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

async function openRecord() {
  window.history.pushState({}, '', `/cmdb/${CI}`);
  render(<Shown />);
  await screen.findByTestId('ci-record');
}

describe('CMDB › raise from a CI', () => {
  it('builds each form address with the template (or item) and the CI', () => {
    expect(ciRaisePath('incident', TEMPLATE, CI)).toBe(
      `/incidents/new?template=${TEMPLATE}&ci=${CI}`,
    );
    expect(ciRaisePath('service_request', ITEM, CI)).toBe(`/requests/new?item=${ITEM}&ci=${CI}`);
    expect(ciRaisePath('change', TEMPLATE, CI)).toBe(`/changes/new?template=${TEMPLATE}&ci=${CI}`);
  });

  it('offers only the kinds you may create, and opens the form with the CI', async () => {
    setDefaultClientFactory(inertClientFactory);
    api(['incidents.create']);
    await openRecord();
    const menu = await openMoreActions('ci-actions');
    expect(within(menu).getByTestId('ci-raise-incident').textContent).toBe('Raise an incident');
    expect(within(menu).queryByTestId('ci-raise-service_request')).toBeNull();
    expect(within(menu).queryByTestId('ci-raise-change')).toBeNull();
    fireEvent.click(within(menu).getByTestId('ci-raise-incident'));
    const dialog = await screen.findByTestId('ci-raise-dialog');
    expect(dialog.textContent).toContain('Raise an incident about this configuration item');
    const pick = within(dialog).getByTestId('ci-raise-template');
    fireEvent.mouseDown(pick.querySelector('input') ?? pick);
    fireEvent.click(await screen.findByText('Server down'));
    fireEvent.click(screen.getByTestId('ci-raise-ok'));
    await waitFor(() => {
      expect(`${window.location.pathname}${window.location.search}`).toBe(
        `/incidents/new?template=${TEMPLATE}&ci=${CI}`,
      );
    });
  });

  it('a request opens with its catalogue item and the CI', async () => {
    setDefaultClientFactory(inertClientFactory);
    api(['requests.create']);
    await openRecord();
    const menu = await openMoreActions('ci-actions');
    fireEvent.click(within(menu).getByTestId('ci-raise-service_request'));
    const dialog = await screen.findByTestId('ci-raise-dialog');
    const pick = within(dialog).getByTestId('ci-raise-template');
    fireEvent.mouseDown(pick.querySelector('input') ?? pick);
    fireEvent.click(await screen.findByText('Disk space'));
    fireEvent.click(screen.getByTestId('ci-raise-ok'));
    await waitFor(() => {
      expect(window.location.search).toBe(`?item=${ITEM}&ci=${CI}`);
    });
  });

  it('without any create right there is nothing to raise', async () => {
    setDefaultClientFactory(inertClientFactory);
    api([]);
    await openRecord();
    expect(screen.queryByTestId('ci-actions-more')).toBeNull();
    expect(screen.queryByTestId('ci-raise-incident')).toBeNull();
  });

  it('reads in Arabic, right to left, with no raw code', async () => {
    setDefaultClientFactory(inertClientFactory);
    api(['incidents.create', 'requests.create', 'changes.create'], 'ar');
    await openRecord();
    await waitFor(() => {
      expect(document.documentElement.dir).toBe('rtl');
    });
    const menu = await openMoreActions('ci-actions');
    expect(within(menu).getByTestId('ci-raise-incident').textContent).toBe('إنشاء حادثة');
    expect(within(menu).getByTestId('ci-raise-change').textContent).toBe('إنشاء طلب تغيير');
    expect(menu.textContent).not.toMatch(/cmdb\.raise|service_request|incident\b/);
  });
});
