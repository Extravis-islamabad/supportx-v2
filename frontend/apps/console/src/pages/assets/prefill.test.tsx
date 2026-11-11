import { render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { AssetRecord, CatalogItem } from '@supportx/api-client';
import {
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-049b s4a (REQ-AST-045), lane A's condition: a create form opened from an asset with IDs in
// its address uses each only once it is known. An unknown or not-allowed template, item, asset
// or person leaves that field empty, quietly: no banner, no toast. The server checks again.

const ITEM_ID = '01a1a2b3-0000-7000-8000-00000000c001';
const UNKNOWN = '01a1a2b3-0000-7000-8000-0000000dead0';
const ASSET_ID = '01a1a2b3-0000-7000-8000-00000000a5e1';
const laptop: CatalogItem = {
  id: ITEM_ID,
  names: { en: 'New laptop', ar: 'حاسوب جديد' },
  summaries: {},
  descriptions: {},
  keywords: {},
  icon: null,
  category_id: null,
  extra_category_ids: [],
  kind: 'service',
  template_id: null,
  audience: 'everyone',
  status: 'published',
  enabled: true,
  publish_at: null,
  retire_at: null,
  published_at: null,
  owner_id: null,
  featured: false,
  sort_order: 0,
  subject_template: null,
  requesters_see_approval: true,
  starter: false,
  missing_translations: [],
  questions: [
    {
      key: 'model',
      label: { en: 'Model' },
      kind: 'choice',
      required: true,
      options: ['air', 'pro'],
    },
  ],
  approval: {
    approvers: [{ kind: 'requested_for_manager', person_id: null }],
    comments_required: false,
    self_approval: false,
  },
  plan: [],
  default_priority: 'p2',
  requester_sets_priority: false,
  sla_policy_id: null,
  group_id: null,
  technician_id: null,
  technician_after_approval: false,
  count_approval_time: false,
  auto_fulfil: true,
  can_manage: true,
  version: 1,
};
const asset = {
  id: ASSET_ID,
  name: 'Finance laptop',
  tag: 'AST-9',
  state_id: '01a1a2b3-0000-7000-8000-00000000a501',
} as AssetRecord;

let restore: () => void = () => undefined;
beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  restore();
});

function api(routes: Record<string, unknown> = {}) {
  const fake = consoleApi({
    me: fakeSession({ roles: ['tenant_admin'] }),
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/incidents/reply-templates': { body: [] },
      'GET /api/v1/incidents/assignees': { body: [] },
      'GET /api/v1/custom-fields': { body: [] },
      // The requester picker's list (a 404 here would toast on its own, prefill or not).
      'GET /api/v1/users': { body: { items: [], next_cursor: null, has_more: false } },
      'GET /api/v1/catalog/items': { body: [laptop] },
      'GET /api/v1/catalog/categories': { body: [] },
      [`GET /api/v1/catalog/items/${ITEM_ID}`]: { body: laptop },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

/** Nothing told the person anything went wrong. */
function noErrorShown() {
  expect(document.querySelector('.ant-message-notice')).toBeNull();
  expect(document.querySelector('.ant-notification-notice')).toBeNull();
  expect(screen.queryByTestId('inc-template-error')).toBeNull();
}

describe('prefill from the address (raised from an asset)', () => {
  it('an unknown template, asset and person leave the incident form empty, with no error', async () => {
    window.history.pushState(
      {},
      '',
      `/incidents/new?template=${UNKNOWN}&asset=${UNKNOWN}&requester=${UNKNOWN}`,
    );
    const fake = api();
    render(<App />);
    const picker = await screen.findByTestId('inc-template');
    // The form's own default, as if no template had been asked for.
    await waitFor(() => {
      expect(picker.querySelector('.ant-select-selection-item')).not.toBeNull();
    });
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/assets/${UNKNOWN}`).length).toBeGreaterThan(0);
    });
    const assets = await screen.findByTestId('inc-assets');
    expect(assets.querySelectorAll('.ant-select-selection-item')).toHaveLength(0);
    expect(document.body.textContent).not.toContain(UNKNOWN);
    noErrorShown();
  });

  it('a known asset is filled in by its tag and name, never its ID', async () => {
    window.history.pushState({}, '', `/incidents/new?asset=${ASSET_ID}`);
    api({ [`GET /api/v1/assets/${ASSET_ID}`]: { body: asset } });
    render(<App />);
    const assets = await screen.findByTestId('inc-assets');
    await waitFor(() => {
      expect(within(assets).getByText('AST-9 · Finance laptop')).toBeTruthy();
    });
    expect(document.body.textContent).not.toContain(ASSET_ID);
  });

  it('an unknown catalogue item keeps the request library open, with no error', async () => {
    window.history.pushState({}, '', `/requests/new?item=${UNKNOWN}&asset=${UNKNOWN}`);
    const fake = api();
    render(<App />);
    expect(await screen.findByTestId(`sr-item-${ITEM_ID}`)).toBeTruthy();
    expect(fake.find('GET', `/api/v1/catalog/items/${UNKNOWN}`)).toHaveLength(0);
    noErrorShown();
  });
});
