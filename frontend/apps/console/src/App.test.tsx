import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { session, stubApi } from './test/api';

describe('console', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.dir = 'ltr';
  });

  it('shows the signed-in user, tenant and a sign-out button in the header', async () => {
    stubApi(session());
    render(<App />);

    expect(await screen.findByTestId('user-name')).toHaveProperty(
      'textContent',
      'Tariq Technician',
    );
    expect(screen.getByTestId('tenant-name').textContent).toBe('Demo Company');
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'SupportX v2' })).toBeDefined();
  });

  it('sends an anonymous visitor to the BFF login, coming back to the same page', async () => {
    stubApi(null);
    const navigate = vi.fn();
    window.history.pushState({}, '', '/tickets?id=7');
    render(<App navigate={navigate} />);

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith(
        '/api/v1/auth/login?app=console&returnTo=%2Ftickets%3Fid%3D7',
      );
    });
    expect(screen.getByText('Redirecting to sign in…')).toBeDefined();
    window.history.pushState({}, '', '/');
  });

  it('follows the user locale: an Arabic user gets Arabic labels right-to-left', async () => {
    stubApi(session({ locale: 'ar' }));
    render(<App />);

    expect(await screen.findByRole('button', { name: 'تسجيل الخروج' })).toBeDefined();
    // The provider applies dir/lang in an effect, just after the labels render: wait for it.
    await waitFor(() => {
      expect(document.documentElement.dir).toBe('rtl');
    });
    expect(document.documentElement.lang).toBe('ar');
  });

  it('logs out with the CSRF token from the session, then asks for a new login', async () => {
    const calls = stubApi(session());
    const navigate = vi.fn();
    render(<App navigate={navigate} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith('/api/v1/auth/login?app=console&returnTo=%2F');
    });
    const logout = calls.find((call) => call.url.endsWith('/auth/logout'));
    expect(logout?.method).toBe('POST');
    expect(logout?.headers.get('X-CSRF-Token')).toBe('csrf-from-session');
    // Safe GETs carry no CSRF header.
    const me = calls.find((call) => call.url.endsWith('/auth/me'));
    expect(me?.headers.has('X-CSRF-Token')).toBe(false);
  });

  it('switches the document to right-to-left from the appearance controls', async () => {
    stubApi(session());
    render(<App />);

    fireEvent.click(await screen.findByRole('switch', { name: 'Right-to-left' }));

    expect(document.documentElement.dir).toBe('rtl');
  });

  it('explains a failed login instead of looping back to Keycloak', async () => {
    stubApi(null);
    const navigate = vi.fn();
    window.history.pushState({}, '', '/?auth_error=no_organization');
    render(<App navigate={navigate} />);

    expect(
      await screen.findByText(
        'Your account is not linked to any organisation yet. Please contact your administrator.',
      ),
    ).toBeDefined();
    expect(navigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in again' }));
    expect(navigate).toHaveBeenCalledWith('/api/v1/auth/login?app=console&returnTo=%2F');
    window.history.pushState({}, '', '/');
  });
});
