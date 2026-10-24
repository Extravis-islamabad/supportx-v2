import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { consoleApi, fakeEntitlements, fakeSession, problem } from './test/api';

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
function at(path: string) {
  window.history.pushState({}, '', path);
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const OTHER = { id: '01900000-0000-7000-8000-00000000a7e2', name: 'Other Company' };

describe('console shell', () => {
  beforeEach(() => {
    at('/');
  });
  afterEach(() => {
    restore();
    document.documentElement.dir = 'ltr';
    sessionStorage.clear();
  });

  it('shows the user, tenant and the sections of the plan', async () => {
    api();
    render(<App />);
    expect((await screen.findByTestId('user-name')).textContent).toBe('Tariq Technician');
    expect(screen.getByTestId('tenant-name').textContent).toBe('Demo Company');
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' });
    for (const name of [
      'Home',
      'Incidents',
      'Service requests',
      'Problems',
      'Changes',
      'Releases',
      'Assets',
      'CMDB',
      'Knowledge',
      'Reports',
    ]) {
      expect(within(nav).getByText(name)).toBeDefined();
    }
    expect(within(nav).queryByText('Admin')).toBeNull(); // technicians are not tenant admins
    expect(await screen.findByRole('heading', { name: 'Welcome, Tariq Technician' })).toBeDefined();
  });

  it('hides sections outside the plan; admins see them locked with an upgrade hint', async () => {
    const essentials = fakeEntitlements({
      edition: 'essentials',
      features: ['incident', 'service_request', 'knowledge', 'sla', 'ai_assist'],
    });
    api({ routes: { 'GET /api/v1/entitlements': { body: essentials } } });
    const { unmount } = render(<App />);
    const nav = await screen.findByRole('navigation', { name: 'Main navigation' });
    await waitFor(() => {
      expect(within(nav).queryByText('Problems')).toBeNull();
    });
    expect(within(nav).getByText('Incidents')).toBeDefined();
    expect(within(nav).getByText('Service requests')).toBeDefined();
    unmount();
    restore();

    api({ me: ADMIN, routes: { 'GET /api/v1/entitlements': { body: essentials } } });
    render(<App />);
    const adminNav = await screen.findByRole('navigation', { name: 'Main navigation' });
    await waitFor(() => {
      expect(within(adminNav).getAllByLabelText('Not in your plan').length).toBe(5);
    });
    fireEvent.click(within(adminNav).getByText('CMDB'));
    expect(
      await screen.findByText(/Your plan does not include this feature. Not included in your plan/),
    ).toBeDefined();
  });

  it('shows a translated "coming soon" page per section', async () => {
    at('/problems');
    api();
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Problems' })).toBeDefined();
    expect(screen.getByText(/being built/)).toBeDefined();
  });

  it('opens the command palette with Ctrl+K and navigates', async () => {
    api();
    render(<App />);
    await screen.findByTestId('user-name');
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const input = await screen.findByRole('combobox', { name: 'Type a page name…' });
    fireEvent.change(input, { target: { value: 'know' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(await screen.findByRole('heading', { name: 'Knowledge' })).toBeDefined();
    expect(window.location.pathname).toBe('/knowledge');
  });

  it('switches tenant through the BFF and reloads the plan of the new tenant', async () => {
    const both = fakeSession(
      {},
      { tenants: [{ id: '01900000-0000-7000-8000-00000000de30', name: 'Demo Company' }, OTHER] },
    );
    const fake = api({
      me: both,
      routes: {
        'POST /api/v1/auth/switch-tenant': {
          body: { ...both, tenant: OTHER, csrf_token: 'csrf-2' },
        },
      },
    });
    render(<App />);
    const switcher = await screen.findByRole('combobox', { name: 'Switch organisation' });
    fireEvent.mouseDown(switcher);
    fireEvent.click(await screen.findByTitle('Other Company'));
    expect(await screen.findByText('You are now working in Other Company.')).toBeDefined();
    const [post] = fake.find('POST', '/api/v1/auth/switch-tenant');
    expect(post?.body).toEqual({ tenant_id: OTHER.id });
    expect(post?.headers.get('X-CSRF-Token')).toBe('csrf-from-session');
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/entitlements').length).toBe(2);
    });
  });

  it('explains a refused tenant switch (no technician seat left)', async () => {
    const both = fakeSession(
      {},
      { tenants: [{ id: '01900000-0000-7000-8000-00000000de30', name: 'Demo Company' }, OTHER] },
    );
    api({
      me: both,
      routes: {
        'POST /api/v1/auth/switch-tenant': {
          status: 403,
          body: problem(403, 'technician_limit_reached'),
        },
      },
    });
    render(<App />);
    fireEvent.mouseDown(await screen.findByRole('combobox', { name: 'Switch organisation' }));
    fireEvent.click(await screen.findByTitle('Other Company'));
    expect(
      await screen.findByText(/All technician seats in your organisation’s plan are in use/),
    ).toBeDefined();
    expect(screen.getByRole('button', { name: /Copy reference/ })).toBeDefined();
  });

  it('sends an anonymous visitor to the BFF login, coming back to the same page', async () => {
    api({ me: null });
    const navigate = vi.fn();
    at('/tickets?id=7');
    render(<App navigate={navigate} />);
    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith(
        '/api/v1/auth/login?app=console&returnTo=%2Ftickets%3Fid%3D7',
      );
    });
  });

  it('follows the user locale: an Arabic user gets Arabic labels right-to-left', async () => {
    api({ me: fakeSession({ locale: 'ar' }) });
    render(<App />);
    expect(await screen.findByRole('navigation', { name: 'التنقل الرئيسي' })).toBeDefined();
    await waitFor(() => {
      expect(document.documentElement.dir).toBe('rtl');
    });
    expect(document.documentElement.lang).toBe('ar');
  });

  it('logs out with the CSRF token from the session, then asks for a new login', async () => {
    const fake = api();
    const navigate = vi.fn();
    render(<App navigate={navigate} />);
    fireEvent.click(await screen.findByTestId('user-menu'));
    fireEvent.click(await screen.findByText('Sign out'));
    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith('/api/v1/auth/login?app=console&returnTo=%2F');
    });
    expect(fake.find('POST', '/api/v1/auth/logout')[0]?.headers.get('X-CSRF-Token')).toBe(
      'csrf-from-session',
    );
    expect(fake.find('GET', '/api/v1/auth/me')[0]?.headers.has('X-CSRF-Token')).toBe(false);
  });

  it('switches theme and direction from the appearance menu', async () => {
    api();
    render(<App />);
    fireEvent.click(await screen.findByTestId('appearance-menu'));
    fireEvent.click(await screen.findByText('High contrast'));
    expect(document.documentElement.dataset.theme).toBe('high_contrast');
    fireEvent.click(screen.getByRole('switch', { name: 'Right-to-left' }));
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('explains a failed login instead of looping back to Keycloak', async () => {
    api({ me: null });
    const navigate = vi.fn();
    at('/?auth_error=technician_limit_reached');
    render(<App navigate={navigate} />);
    expect(
      await screen.findByText(/All technician seats in your organisation’s plan are in use/),
    ).toBeDefined();
    expect(navigate).not.toHaveBeenCalled();
  });

  it('shows a not-found page for unknown addresses', async () => {
    at('/nowhere');
    api();
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeDefined();
  });

  it('shows the reconnecting banner when the API stops answering', async () => {
    api({ routes: { 'GET /api/v1/health': 'network-error' } });
    render(<App />);
    // The health tag is silent (it is its own message); the banner still reports the outage.
    expect(await screen.findByTestId('reconnecting-banner')).toBeDefined();
  });
});
