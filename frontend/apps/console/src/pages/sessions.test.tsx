import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { ListedSession, UserDetail } from '@supportx/api-client';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../App';
import { consoleApi, fakeSession, fakeUser } from '../test/api';

// ADR-044 item 5: My account lists your signed-in browsers and devices; people admins see a
// person's, and either can sign one out at once.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const THIS: ListedSession = {
  id: 'a'.repeat(32),
  client: 'console',
  platform: null,
  app_version: null,
  started_at: '2026-11-06T07:00:00Z',
  last_used_at: '2026-11-06T08:00:00Z',
  current: true,
};
const PHONE: ListedSession = {
  ...THIS,
  id: 'b'.repeat(32),
  client: 'mobile',
  platform: 'ios',
  app_version: '1.0.3',
  current: false,
};

/** The OK button of the open confirmation (a drawer is a dialog too, so find the confirm). */
async function confirm(name: string) {
  const dialog = await waitFor(() => {
    const found = document.querySelector<HTMLElement>('.ant-modal-confirm');
    if (found === null) throw new Error('no confirmation open');
    return found;
  });
  fireEvent.click(within(dialog).getByRole('button', { name }));
}

describe('My account › signed-in devices', () => {
  it('lists them, this one marked and kept; another is signed out after asking', async () => {
    window.history.pushState({}, '', '/profile');
    let rows = [THIS, PHONE];
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/auth/sessions': () => ({ body: rows }),
        [`DELETE /api/v1/auth/sessions/${PHONE.id}`]: () => {
          rows = [THIS];
          return { status: 204 };
        },
      },
    });
    render(<App />);
    const card = await screen.findByTestId('account-sessions');
    const phone = await within(card).findByTestId(`session-${PHONE.id}`);
    expect(phone.textContent).toContain('SupportX app on iPhone or iPad');
    expect(phone.textContent).toContain('version 1.0.3');
    const mine = within(card).getByTestId(`session-${THIS.id}`);
    expect(mine.textContent).toContain('Console in a browser');
    expect(mine.textContent).toContain('This device');
    expect(within(mine).queryByRole('button')).toBeNull(); // this one is signed out by Sign out
    fireEvent.click(within(phone).getByTestId(`session-end-${PHONE.id}`));
    await confirm('Sign out');
    await waitFor(() => {
      expect(fake.find('DELETE', `/api/v1/auth/sessions/${PHONE.id}`)).toHaveLength(1);
    });
    await waitFor(() => {
      expect(within(card).queryByTestId(`session-${PHONE.id}`)).toBeNull();
    });
  });

  it('a sign-in elsewhere shows up live, with no refresh', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/profile');
    let rows = [THIS];
    api({ me: ADMIN, routes: { 'GET /api/v1/auth/sessions': () => ({ body: rows }) } });
    render(<App />);
    const card = await screen.findByTestId('account-sessions');
    await within(card).findByTestId(`session-${THIS.id}`);
    rows = [THIS, PHONE];
    act(() => {
      realtime.publish(`:user:${ADMIN.user.id}`, {
        type: 'identity_access.sessions_changed',
        ids: [],
      });
    });
    expect(await within(card).findByTestId(`session-${PHONE.id}`)).toBeTruthy();
  });
});

describe('Admin › People › Devices', () => {
  it('a people admin sees a person’s devices and signs one out (a lost phone)', async () => {
    const bilal: UserDetail = fakeUser({ id: 'u-9', display_name: 'Bilal Saleh' });
    window.history.pushState({}, '', '/admin/users');
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/users': { body: { items: [bilal], has_more: false, next_cursor: null } },
        'GET /api/v1/access-settings': {
          body: { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 },
        },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/organization/departments': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'GET /api/v1/users/u-9': { body: bilal, headers: { ETag: '"1"' } },
        'GET /api/v1/identity/people/u-9/sessions': { body: [{ ...PHONE, current: false }] },
        [`DELETE /api/v1/identity/people/u-9/sessions/${PHONE.id}`]: { status: 204 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByText('Bilal Saleh'));
    fireEvent.click(await screen.findByRole('tab', { name: 'Devices' }));
    fireEvent.click(await screen.findByTestId(`session-end-${PHONE.id}`));
    await confirm('Sign out');
    await waitFor(() => {
      expect(fake.find('DELETE', `/api/v1/identity/people/u-9/sessions/${PHONE.id}`)).toHaveLength(
        1,
      );
    });
  });
});
