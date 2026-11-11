import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';

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
  repeat: 'none',
  repeat_week: null,
  repeat_weekday: null,
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
      'GET /api/v1/changes/settings': {
        body: { ...fakeIncidentCatalogue(), outside_maintenance_blocks: false, version: 4 },
      },
      'PATCH /api/v1/changes/settings': {
        body: { ...fakeIncidentCatalogue(), outside_maintenance_blocks: true, version: 5 },
      },
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

  it('D-156: a monthly window is made on its week and day', async () => {
    window.history.pushState({}, '', '/admin/change-windows');
    const fake = api();
    render(<App />);
    fireEvent.click(await screen.findByTestId('window-add'));
    const editor = await screen.findByTestId('window-editor');
    fireEvent.change(within(editor).getByTestId('window-name-en'), {
      target: { value: 'First Sunday' },
    });
    for (const [id, value] of [
      ['window-starts', '7 Mar 2027 02:00'],
      ['window-ends', '7 Mar 2027 06:00'],
    ] as const) {
      const input = within(editor).getByTestId(id);
      fireEvent.mouseDown(input);
      fireEvent.change(input, { target: { value } });
      fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    }
    const choose = async (testId: string, title: string) => {
      const select = within(editor).getByTestId(testId).querySelector('.ant-select-selector');
      if (select === null) throw new Error('not an Ant Design Select');
      fireEvent.mouseDown(select);
      fireEvent.click(await screen.findByTitle(title));
    };
    await choose('window-repeat', 'Every month');
    await choose('window-week', 'First');
    await choose('window-weekday', 'Sunday');
    fireEvent.click(screen.getByTestId('edit-ok'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/change-windows')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/change-windows')[0]?.body).toMatchObject({
      repeat: 'monthly',
      repeat_weekly: false,
      repeat_week: 1,
      repeat_weekday: 6,
    });
  });

  it('D-156: the tenant switches outside-maintenance to block, with the version shown', async () => {
    window.history.pushState({}, '', '/admin/change-windows');
    const fake = api();
    render(<App />);
    fireEvent.click(await screen.findByTestId('windows-outside-blocks'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/changes/settings')).toHaveLength(1);
    });
    const [saved] = fake.find('PATCH', '/api/v1/changes/settings');
    expect(saved?.headers.get('If-Match')).toBe('"4"');
    expect(saved?.body).toEqual({ outside_maintenance_blocks: true });
  });
});
