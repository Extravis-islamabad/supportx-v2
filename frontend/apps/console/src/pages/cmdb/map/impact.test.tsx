import { render, screen, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-053 S3b: the CI's Impact tab (REQ-CMDB-010, 030). A CI the reader can't open is a bare
// row in words with no link, a path through it still shows, affected users say "not
// configured", and truncation is said in words; no raw code reaches the screen.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const TYPE = 'a0000000-0000-7000-8000-000000000001';
const STATE = 'a0000000-0000-7000-8000-000000000002';
const CI = 'a0000000-0000-7000-8000-000000000003';
const OTHER = 'a0000000-0000-7000-8000-000000000004';
// The CI's references, named by the server for the reader (CMDB polish).
const SITE = 'a0000000-0000-7000-8000-000000000006';
const PERSON = 'a0000000-0000-7000-8000-000000000008';
const named = (label: string) => ({ label, restricted: false, gone: false });
const now = new Date().toISOString();

const ci = {
  id: CI,
  display_id: 'CI-1',
  name: 'Mail service',
  type_id: TYPE,
  state_id: STATE,
  site_id: SITE,
  owner_user_id: PERSON,
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
  // 0175 part 2: custom values the person may read, and what their field rules withhold.
  custom: {},
  masked_fields: [],
  read_only_fields: [],
  names: { [SITE]: named('Islamabad HQ'), [PERSON]: named('Sara Khan') },
};

const node = (id: string, name: string, display: string) => ({
  key: id,
  restricted: false,
  depth: id === CI ? 0 : 1,
  id,
  display_id: display,
  name,
  type_id: TYPE,
  type_label_key: 'cmdb_ci_type.server',
  type_names: {},
  state_id: STATE,
  state_category: 'active',
  state_label_key: 'cmdb_ci_state.in_use',
  state_names: {},
  version: 1,
  counts: null,
});

const SERVICE = 'a0000000-0000-7000-8000-000000000009';

function impact(truncated = false) {
  return {
    start: { ...node(CI, 'Mail service', 'CI-1'), via: null },
    cis: [
      { key: 'r1', restricted: true, depth: 1, via: CI, type_names: {}, state_names: {} },
      { ...node(OTHER, 'Mail app', 'CI-2'), depth: 2, via: 'r1' },
      { ...node(SERVICE, 'Email for staff', 'CI-3'), depth: 3, via: OTHER },
    ],
    services: [{ id: SERVICE, name: 'Email for staff' }],
    restricted: 1,
    affected_users: null,
    affected_users_reason: 'not_configured',
    truncated,
    depth: 3,
    ci_max: 5000,
    as_of: now,
  };
}

function api(truncated = false) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/custom-fields': { body: [] },
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/cmdb/ci-states': { body: { items: [] } },
      'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
      [`GET /api/v1/cmdb/cis/${CI}`]: { body: ci, headers: { ETag: '"3"' } },
      [`GET /api/v1/cmdb/cis/${CI}/history`]: {
        body: { items: [], has_more: false, next_cursor: null },
      },
      [`GET /api/v1/cmdb/cis/${CI}/impact`]: { body: impact(truncated) },
      'GET /api/v1/realtime/lists/cmdb': { body: { channels: ['t:tenant:cmdb:all'] } },
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

describe('CMDB › the Impact tab', () => {
  it('lists what a failure reaches, a restricted CI in words, and the path through it', async () => {
    setDefaultClientFactory(inertClientFactory);
    api();
    window.history.pushState({}, '', `/cmdb/${CI}?tab=impact`);
    render(<Shown />);
    const tab = await screen.findByTestId('ci-impact-tab');
    const rows = await within(tab).findAllByTestId('ci-impact-row');
    expect(rows).toHaveLength(3);
    const [restricted, app] = rows;
    expect(restricted?.textContent).toContain("A CI you can't open");
    expect(restricted?.querySelector('a')).toBeNull();
    expect(restricted?.textContent).not.toContain('r1');
    // The app is reached through the restricted CI: the path names it in words, never its key.
    expect(app?.textContent).toContain("Through A CI you can't open");
    expect(app?.querySelector('a')?.getAttribute('href')).toBe(`/cmdb/cis/${OTHER}`);
    expect(within(tab).getByTestId('ci-impact-services').textContent).toContain('Email for staff');
    const summary = within(tab).getByTestId('ci-impact-summary');
    expect(summary.textContent).toContain('Not configured');
    expect(summary.textContent).toContain("CIs you can't open");
    expect(screen.queryByTestId('ci-impact-truncated')).toBeNull();
    expect(tab.textContent).not.toMatch(/not_configured|cmdb_|dependents|in_use|r1/);
  });

  it('says a cut answer in words', async () => {
    setDefaultClientFactory(inertClientFactory);
    api(true);
    window.history.pushState({}, '', `/cmdb/${CI}?tab=impact`);
    render(<Shown />);
    const cut = await screen.findByTestId('ci-impact-truncated');
    expect(cut.textContent).toContain('Only the first 5000 CIs are shown');
  });
});
