import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { session, stubApi } from './test/api';

describe('portal', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.dir = 'ltr';
  });

  it('shows the signed-in requester and the portal name', async () => {
    stubApi(session({ display_name: 'Yusra Requester', user_type: 'requester' }));
    render(<App />);

    expect((await screen.findByTestId('user-name')).textContent).toBe('Yusra Requester');
    expect(screen.getByText('Self-Service Portal')).toBeDefined();
  });

  it('uses the portal login when there is no session', async () => {
    stubApi(null);
    const navigate = vi.fn();
    render(<App navigate={navigate} />);

    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith('/api/v1/auth/login?app=portal&returnTo=%2F');
    });
  });

  it('renders right-to-left for an Arabic requester', async () => {
    stubApi(session({ locale: 'ar', user_type: 'requester' }));
    render(<App />);

    expect(await screen.findByRole('button', { name: 'تسجيل الخروج' })).toBeDefined();
    expect(document.documentElement.dir).toBe('rtl');
  });

  it('switches the document to right-to-left from the appearance controls', async () => {
    stubApi(session());
    render(<App />);

    fireEvent.click(await screen.findByRole('switch', { name: 'Right-to-left' }));

    expect(document.documentElement.dir).toBe('rtl');
  });
});
