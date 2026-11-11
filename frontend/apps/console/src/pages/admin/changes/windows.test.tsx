import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-045c S3: freeze and maintenance windows on template E. A new freeze blocks and a
// maintenance window warns (D-156, held); the change manager and admins edit them.

const FREEZE = '01a1a2b3-0000-7000-8000-0000000f0003';

const window_ = {
  id: FREEZE,
  kind: 'freeze',
  mode: 'block',
  name: 'Quarter end',
  labels: null,
  description: null,
  starts_at: '2027-03-29T00:00:00Z',
  ends_at: '2027-03-31T00:00:00Z',
  repeat_weekly: false,
  repeat_until: null,
  site_ids: [],
  group_ids: [],
  service_ids: [],
  ci_ids: [],
  version: 2,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(permissions = ['changes.view', 'changes.manage_windows']) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['change_manager'] },
      {
        permissions: permissions.map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      'GET /api/v1/change-windows': { body: [window_] },
      'POST /api/v1/change-windows': { status: 201, body: { ...window_, id: 'new' } },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: freeze and maintenance windows', () => {
  it('lists windows and, for a new one, the kind sets its default mode (D-156)', async () => {
    window.history.pushState({}, '', '/admin/change-windows');
    api();
    render(<App />);
    const table = await screen.findByTestId('windows-table');
    await waitFor(() => {
      expect(table.textContent).toContain('Quarter end');
    });
    expect(table.textContent).toContain('The whole organisation');
    fireEvent.click(screen.getByTestId('window-add'));
    const editor = await screen.findByTestId('window-editor');
    expect(within(editor).getByTestId('window-mode').textContent).toContain('Blocks changes');
    const kind = within(editor).getByTestId('window-kind').querySelector('.ant-select-selector');
    if (kind === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(kind);
    fireEvent.click(await screen.findByTitle('Maintenance window'));
    expect(within(editor).getByTestId('window-mode').textContent).toContain('Warns only');
  });

  it('settings.manage manages the windows too', async () => {
    window.history.pushState({}, '', '/admin/change-windows');
    api(['changes.view', 'settings.manage']);
    render(<App />);
    expect(await screen.findByTestId('windows-table')).toBeTruthy();
    expect(screen.getByTestId('window-add')).toBeTruthy();
  });
});
