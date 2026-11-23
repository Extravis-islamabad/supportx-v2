import { fireEvent, render, screen, within } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';

import { fakePermissions, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-053 S4b (REQ-CMDB-018): import CIs or relationships. A dry run first; its result in words,
// each refused row by its column and reason (never a code), and the refused rows downloaded
// from the server (formula-safe, in the reader's language).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const JOB = 'a0000000-0000-7000-8000-000000000201';
const now = new Date().toISOString();
const checked = {
  id: JOB,
  kind: 'relationships',
  mode: 'add_update',
  match_on: 'display_id',
  type_id: null,
  dry_run: true,
  file_name: 'links.csv',
  file_format: 'csv',
  status: 'checked',
  total: 3,
  processed: 3,
  created_count: 1,
  updated_count: 0,
  unchanged_count: 1,
  failed_count: 1,
  problems: [{ row: 3, field: 'to', code: 'not_found' }],
  failure: null,
  failure_detail: null,
  created_at: now,
  checked_at: now,
  finished_at: null,
  version: 4,
};

// An administrator who may add and edit CIs (cmdb.manage).
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
      'GET /api/v1/cmdb/ci-types': { body: { items: [] } },
      'GET /api/v1/cmdb/ci-states': { body: { items: [] } },
      'GET /api/v1/cmdb/cis': { body: { items: [], has_more: false, next_cursor: null } },
      'POST /api/v1/cmdb/imports': { status: 201, body: { ...checked, status: 'queued' } },
      [`GET /api/v1/cmdb/imports/${JOB}`]: { body: checked },
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

describe('CMDB › importing CIs and relationships', () => {
  it('checks the file first and names each refused row in words', async () => {
    setDefaultClientFactory(inertClientFactory);
    api();
    window.history.pushState({}, '', '/cmdb');
    render(<Shown />);
    fireEvent.click(await screen.findByTestId('cmdb-import'));
    const drawer = await screen.findByTestId('ci-import-drawer');
    const kind = within(drawer).getByTestId('ci-import-kind');
    fireEvent.mouseDown(kind.querySelector('input') ?? kind);
    fireEvent.click(await screen.findByText('Relationships'));
    // The fake API reads a body as JSON, so the file's bytes are a JSON value here.
    const file = new File(['1'], 'links.csv', { type: 'text/csv' });
    fireEvent.change(within(drawer).getByTestId('ci-import-file'), { target: { files: [file] } });
    fireEvent.click(within(drawer).getByTestId('ci-import-check'));
    const would = await within(drawer).findByTestId('ci-import-would');
    expect(would.textContent).toContain('Would add 1');
    const problems = within(drawer).getByTestId('ci-import-problems');
    expect(problems.textContent).toContain('To');
    expect(problems.textContent).not.toContain('not_found');
    const download = within(drawer).getByTestId('ci-import-download-problems');
    expect(download.getAttribute('href')).toBe(`/api/v1/cmdb/imports/${JOB}/problems?language=en`);
    expect(within(drawer).getByTestId('ci-import-run')).toBeTruthy();
  });
});
