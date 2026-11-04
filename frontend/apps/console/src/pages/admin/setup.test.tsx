import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeEntitlements, fakeSession, type FakeRoute } from '@supportx/api-client/testing';
import { en } from '@supportx/labels';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { routes } from '../../router';
import { consoleApi } from '../../test/api';
import { fold, matches, SETUP_GROUPS, SETUP_PAGES } from './setupMap';

// WP-042 session 1: the setup home, menu and search (REQ-ADM-106–108), the licence page (109).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });

function api(routes: Record<string, FakeRoute> = {}, me = ADMIN) {
  const fake = consoleApi({ me, routes });
  restore = fake.restore;
  return fake;
}

describe('the setup map', () => {
  it('holds every admin route, once', () => {
    const admin = routes[0]?.children?.find((route) => route.path === 'admin');
    const paths = (admin?.children ?? [])
      .map((route) => route.path?.split('/')[0])
      .filter((path): path is string => path !== undefined);
    const keys = SETUP_PAGES.map((page) => page.key);
    // Sub-pages of a setup page (integrations/directories) share its key.
    expect([...new Set(paths)].sort()).toEqual([...new Set(keys)].sort());
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('every page and group has its labels in English', () => {
    const missing = [
      ...SETUP_GROUPS.map((group) => `setup.group.${group}`),
      ...SETUP_PAGES.flatMap((page) => [
        page.labelKey,
        `setup.page.${page.key}.description`,
        `setup.page.${page.key}.keywords`,
      ]),
    ].filter((key) => !(key in en));
    expect(missing).toEqual([]);
  });

  it('search folds case, punctuation and Arabic letter forms', () => {
    expect(fold('Sign-In')).toBe('signin');
    expect(fold('أمان')).toBe(fold('امان'));
    expect(matches('pass word', ['Password policy'])).toBe(true); // every word, anywhere
    expect(matches('mfa sso', ['Password, MFA'])).toBe(false);
    expect(matches('password', ['Sign-in', 'Password, MFA'])).toBe(true);
    expect(matches('', ['anything'])).toBe(true);
  });
});

describe('Setup home and menu', () => {
  it('groups the pages this person may open, each with its explanation', async () => {
    window.history.pushState({}, '', '/admin');
    api();
    render(<App />);
    const home = await screen.findByTestId('setup-home');
    expect(within(home).getByRole('heading', { name: 'People and access' })).toBeDefined();
    expect(within(home).getByTestId('setup-page-users').textContent).toBe('People');
    expect(home.textContent).toContain('Add people, change their type and status');
    const menu = screen.getByTestId('admin-sections');
    expect(within(menu).getByTestId('admin-sections-home').getAttribute('aria-current')).toBe(
      'page',
    );
    expect(within(menu).getByTestId('admin-sections-licence')).toBeDefined();
  });

  it('a technician sees no setup page they may not open', async () => {
    window.history.pushState({}, '', '/admin');
    api({}, fakeSession());
    render(<App />);
    await waitFor(() => {
      expect(screen.queryByTestId('admin-sections-licence')).toBeNull();
    });
    expect(screen.queryByTestId('admin-sections-security')).toBeNull();
  });

  it('finds a page by a synonym, and says when nothing matches', async () => {
    window.history.pushState({}, '', '/admin');
    api();
    render(<App />);
    const search = await screen.findByTestId('setup-search');
    fireEvent.change(search.querySelector('input') ?? search, { target: { value: '2fa' } });
    const home = screen.getByTestId('setup-home');
    expect(within(home).getByTestId('setup-page-security')).toBeDefined();
    expect(within(home).queryByTestId('setup-page-users')).toBeNull();
    fireEvent.change(search.querySelector('input') ?? search, { target: { value: 'zzzz' } });
    expect(await within(home).findByTestId('setup-no-results')).toBeDefined();
  });
});

describe('Licence and plan', () => {
  it('shows the edition, state, limits with usage and features, in labels', async () => {
    window.history.pushState({}, '', '/admin/licence');
    api({
      'GET /api/v1/entitlements': {
        body: fakeEntitlements({
          limits: [{ key: 'technicians', limit: 25, used: 7, remaining: 18 }],
        }),
      },
    });
    render(<App />);
    const page = await screen.findByTestId('licence-page');
    expect(within(page).getByTestId('licence-edition').textContent).toBe('Enterprise');
    expect(within(page).getByTestId('licence-limits').textContent).toContain('Technicians');
    expect(within(page).getByTestId('licence-limits').textContent).toContain('7 of 25');
    expect(within(page).getByTestId('licence-features').textContent).toContain(
      'Incident Management',
    );
    expect(page.textContent).not.toMatch(/technicians|enterprise|incident_management/);
  });

  it('refetches the usage when a technician is added elsewhere', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/admin/licence');
    let used = 7;
    const fake = api({
      'GET /api/v1/entitlements': () => ({
        body: fakeEntitlements({
          limits: [{ key: 'technicians', limit: 25, used, remaining: 25 - used }],
        }),
      }),
    });
    render(<App />);
    const limits = await screen.findByTestId('licence-limits');
    expect(limits.textContent).toContain('7 of 25');
    used = 8;
    await waitFor(() => {
      expect(realtime.channels().some((name) => name.endsWith(':broadcast'))).toBe(true);
    });
    act(() => {
      realtime.publish(':broadcast', { type: 'entitlements.usage_changed', ids: [] });
    });
    await waitFor(() => {
      expect(screen.getByTestId('licence-limits').textContent).toContain('8 of 25');
    });
    expect(fake.find('GET', '/api/v1/entitlements').length).toBeGreaterThan(1);
  });
});

describe('Setup in the command palette (REQ-ADM-107)', () => {
  it('finds a setup page by a keyword once something is typed', async () => {
    window.history.pushState({}, '', '/');
    api();
    render(<App />);
    await screen.findByTestId('user-name');
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = await screen.findByRole('combobox', { name: 'Type a page name…' });
    expect(screen.queryByText('Setup › Sign-in and security')).toBeNull(); // not before typing
    fireEvent.change(input, { target: { value: '2fa' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => {
      expect(window.location.pathname).toBe('/admin/security');
    });
  });
});
