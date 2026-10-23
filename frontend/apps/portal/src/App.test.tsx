import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { MeResponse } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

let restore: () => void = () => undefined;
function api(me: MeResponse | null, entitlements = fakeEntitlements()) {
  const fake = fakeApi({
    'GET /api/v1/auth/me':
      me === null
        ? { status: 401, body: { code: 'unauthenticated', message_key: 'errors.unauthenticated' } }
        : { body: me },
    'GET /api/v1/entitlements': { body: entitlements },
  });
  restore = fake.restore;
}
const REQUESTER = fakeSession({
  display_name: 'Yusra Requester',
  user_type: 'requester',
  roles: ['requester'],
});

describe('portal', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/');
  });
  afterEach(() => {
    restore();
    document.documentElement.dir = 'ltr';
  });

  it('shows the signed-in requester, the portal name and its simple navigation', async () => {
    api(REQUESTER);
    render(<App />);
    expect((await screen.findByTestId('user-name')).textContent).toBe('Yusra Requester');
    expect(screen.getAllByText('Self-Service Portal').length).toBeGreaterThan(0);
    fireEvent.click(await screen.findByText('My requests'));
    expect(await screen.findByRole('heading', { name: 'My requests' })).toBeDefined();
    expect(screen.queryByTestId('tenant-switcher')).toBeNull();
  });

  it('uses the portal login when there is no session', async () => {
    api(null);
    const navigate = vi.fn();
    render(<App navigate={navigate} />);
    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith('/api/v1/auth/login?app=portal&returnTo=%2F');
    });
  });

  it('renders right-to-left for an Arabic requester', async () => {
    api({ ...REQUESTER, user: { ...REQUESTER.user, locale: 'ar' } });
    render(<App />);
    expect(await screen.findByText('طلباتي')).toBeDefined();
    await waitFor(() => {
      expect(document.documentElement.dir).toBe('rtl');
    });
  });

  it('shows the read-only banner to requesters too', async () => {
    api(
      REQUESTER,
      fakeEntitlements({ state: 'read_only', state_reason: 'suspended', writable: false }),
    );
    render(<App />);
    expect((await screen.findByTestId('read-only-banner')).textContent).toContain(
      'The subscription is suspended.',
    );
  });
});
