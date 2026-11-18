import { fireEvent, render, screen } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// The CI record's edit beaten by someone else's save (#524, lane C's review): the shared
// ConflictDialog opens, the person's edit stays (CLAUDE.md rule g).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const TYPE = 'a0000000-0000-7000-8000-000000000001';
const STATE = 'a0000000-0000-7000-8000-000000000002';
const CI = 'a0000000-0000-7000-8000-000000000003';
const now = new Date().toISOString();

const ci = {
  id: CI,
  display_id: 'CI-1',
  name: 'Core switch SW-01',
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
  version: 1,
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
};

function Shown() {
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App />
    </ConfigProvider>
  );
}

describe('CMDB › a CI edit someone else beat', () => {
  it('opens the shared conflict dialog on a 409 version_conflict', async () => {
    setDefaultClientFactory(inertClientFactory);
    const fake = consoleApi({
      routes: {
        // The CI type's custom fields (0175 part 2): none here.
        'GET /api/v1/custom-fields': { body: [] },
        'GET /api/v1/cmdb/ci-types': {
          body: {
            items: [
              {
                id: TYPE,
                parent_id: null,
                api_name: 'server',
                built_in: true,
                names: {},
                icon: null,
                ci_count: 1,
                child_count: 0,
                version: 1,
              },
            ],
          },
        },
        'GET /api/v1/cmdb/ci-states': {
          body: {
            items: [
              {
                id: STATE,
                api_name: 'live',
                built_in: true,
                names: {},
                category: 'active',
                position: 0,
                version: 1,
              },
            ],
          },
        },
        'GET /api/v1/cmdb/settings': { body: { exclude_eol_from_pickers: true, version: 1 } },
        [`GET /api/v1/cmdb/cis/${CI}`]: { body: ci, headers: { ETag: '"1"' } },
        [`GET /api/v1/cmdb/cis/${CI}/history`]: {
          body: { items: [], has_more: false, next_cursor: null },
        },
        [`PATCH /api/v1/cmdb/cis/${CI}`]: {
          status: 409,
          body: {
            type: 'about:blank',
            title: 'Conflict',
            status: 409,
            code: 'version_conflict',
            message_key: 'errors.version_conflict',
            params: { expected_version: 1, current_version: 2 },
          },
        },
      },
    });
    restore = fake.restore;
    window.history.pushState({}, '', `/cmdb/${CI}`);
    render(<Shown />);
    fireEvent.click(await screen.findByTestId('ci-edit'));
    fireEvent.change(await screen.findByTestId('ci-name'), {
      target: { value: 'Core switch SW-01 (floor 2)' },
    });
    fireEvent.click(screen.getByTestId('ci-save'));
    expect(await screen.findByTestId('conflict-keep-mine')).toBeDefined();
  });
});
