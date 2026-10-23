import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { MeResponse } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

let restore: () => void = () => undefined;
function api(
  me: MeResponse | null,
  entitlements = fakeEntitlements(),
  feed: unknown = { items: [], next_change_in_seconds: null },
) {
  const fake = fakeApi({
    'GET /api/v1/auth/me':
      me === null
        ? { status: 401, body: { code: 'unauthenticated', message_key: 'errors.unauthenticated' } }
        : { body: me },
    'GET /api/v1/entitlements': { body: entitlements },
    'GET /api/v1/announcements/feed': { body: feed },
  });
  restore = fake.restore;
  return fake;
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

  it('home lists the announcements live for the requester, in words, from the portal', async () => {
    const fake = api(REQUESTER, fakeEntitlements(), {
      items: [
        {
          kind: 'public',
          id: 'a1',
          display_id: 'ANN-1',
          title: 'Mail outage',
          body: 'Mail is down.\nWe are on it.',
          severity: 'critical',
          show_as_banner: true,
          published_at: '2026-10-23T10:00:00Z',
          publish_until: null,
          visibility: 'live',
          next_change_in_seconds: null,
        },
      ],
      next_change_in_seconds: null,
    });
    render(<App />);
    expect(await screen.findByText('Critical: Mail outage')).toBeDefined();
    // The full text is on the home page, so no banner repeats it there.
    expect(screen.queryByTestId('announcement-banners')).toBeNull();
    const call = fake.find('GET', '/api/v1/announcements/feed')[0];
    expect(call?.headers.get('X-SupportX-Client')).toBe('portal');
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
