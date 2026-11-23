import { render, screen, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// 0185 (D-172 (3)): a business service's subscribers on its record. Each unit by name, a removed
// one marked "Removed", one the reader may not see "Hidden from you" (never its ID), and how many
// people they reach; nothing at all for a CI that isn't a business service.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const TYPE = 'a0000000-0000-7000-8000-000000000001';
const STATE = 'a0000000-0000-7000-8000-000000000002';
const CI = 'a0000000-0000-7000-8000-000000000003';
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

const DEPT = 'a0000000-0000-7000-8000-000000000011';
const GROUP = 'a0000000-0000-7000-8000-000000000012';

function api(businessService: boolean) {
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
      [`GET /api/v1/cmdb/cis/${CI}/subscribers`]: {
        body: {
          business_service: businessService,
          people: 42,
          items: businessService
            ? [
                {
                  kind: 'department',
                  ref_id: DEPT,
                  name: { label: 'Finance', restricted: false, gone: false },
                  removed: true,
                },
                {
                  kind: 'group',
                  ref_id: GROUP,
                  name: { label: null, restricted: true, gone: false },
                  removed: false,
                },
              ]
            : [],
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

describe("CMDB › a business service's subscribers", () => {
  it('names each unit, marks a removed one and hides an unseen one, with the people reached', async () => {
    setDefaultClientFactory(inertClientFactory);
    api(true);
    window.history.pushState({}, '', `/cmdb/${CI}`);
    render(<Shown />);
    const section = await screen.findByTestId('ci-subscribers');
    expect(section.textContent).toContain('People reached: 42');
    const rows = within(section).getAllByTestId('ci-subscriber');
    expect(rows[0]?.textContent).toContain('Department');
    expect(rows[0]?.textContent).toContain('Finance');
    expect(rows[0]?.textContent).toContain('Removed');
    expect(rows[1]?.textContent).toContain('Hidden from you');
    expect(section.textContent).not.toContain(GROUP);
    expect(section.textContent).not.toMatch(/audience_kind|department\b|cmdb\./);
  });

  it('shows nothing for a CI that is not a business service', async () => {
    setDefaultClientFactory(inertClientFactory);
    api(false);
    window.history.pushState({}, '', `/cmdb/${CI}`);
    render(<Shown />);
    await screen.findByTestId('ci-panel');
    expect(screen.queryByTestId('ci-subscribers')).toBeNull();
  });
});
