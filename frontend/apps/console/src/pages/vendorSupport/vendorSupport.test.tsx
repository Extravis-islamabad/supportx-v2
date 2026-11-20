import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { useCreateSupportGrant, type SupportGrantMade } from '@supportx/api-client';
import { fakeApi, fakeSession, problem } from '@supportx/api-client/testing';

import { App } from '../../App';
import { requesterOnly } from '../../requesterOnly';
import { shownName } from '../../maskedPeople';
import { consoleApi } from '../../test/api';
import { recaptureForTests } from './supportLink';

// WP-057 S4c-3: the engineer's link page, the one-time password, and the support session.
// Lane B's conditions (1), (3), (5), the coordinator's (2): the token never leaves the page in
// a URL, the password is kept nowhere once shown, every failure reads the same.

const TOKEN = 'tok-9f3b2c1d8e7a6f5b4c3d2e1f0a9b8c7d';
const PASSWORD = 'Temp-Pass-7Qx!-not-kept';

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  window.history.pushState({}, '', '/');
  localStorage.clear();
  sessionStorage.clear();
});

function storageHolds(text: string): boolean {
  const dump = [localStorage, sessionStorage].flatMap((store) =>
    Object.keys(store).map((k) => `${k}=${store.getItem(k) ?? ''}`),
  );
  return dump.some((entry) => entry.includes(text));
}

describe('the vendor support link page', () => {
  it('reads the token from the fragment once, clears it, and sends it only in the POST body', async () => {
    window.history.pushState({}, '', `/vendor-support/start?t=acme#${TOKEN}`);
    recaptureForTests();
    // Gone from the address bar before anything renders (lane B (1)).
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain(TOKEN);
    const fake = consoleApi({
      me: null,
      routes: {
        'POST /api/v1/public/vendor-support/open': {
          body: { login: 'sx-support-0a1b', password: PASSWORD },
        },
      },
    });
    restore = fake.restore;
    const { unmount } = render(<App />);
    fireEvent.click(await screen.findByTestId('support-start-open'));
    const shown = await screen.findByTestId<HTMLInputElement>('support-start-password');
    expect(shown.value).toBe(PASSWORD);
    const opened = fake.calls.filter((c) => c.path === '/api/v1/public/vendor-support/open');
    expect(opened).toHaveLength(1);
    expect(opened[0]?.body).toEqual({ token: TOKEN, tenant: 'acme' });
    // No request URL ever holds the token (the coordinator's (2)).
    expect(fake.calls.every((c) => !c.url.toString().includes(TOKEN))).toBe(true);
    expect(document.querySelector('meta[name="referrer"]')?.getAttribute('content')).toBe(
      'no-referrer',
    );
    unmount();
    // Nothing kept: not the page, not web storage (lane B (3)).
    expect(document.body.textContent).not.toContain(PASSWORD);
    expect(storageHolds(PASSWORD)).toBe(false);
    expect(storageHolds(TOKEN)).toBe(false);
  });

  it('ignores a token in the query string (only the fragment counts)', async () => {
    window.history.pushState({}, '', `/vendor-support/start?token=${TOKEN}`);
    recaptureForTests();
    const fake = consoleApi({ me: null });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByText(/Open the link from your e-mail/)).toBeDefined();
    expect(screen.queryByTestId('support-start-open')).toBeNull();
    expect(fake.calls.some((c) => c.path === '/api/v1/public/vendor-support/open')).toBe(false);
  });

  it('says one thing for every failure, and asks only once', async () => {
    window.history.pushState({}, '', `/vendor-support/start#${TOKEN}`);
    recaptureForTests();
    const fake = consoleApi({
      me: null,
      routes: {
        'POST /api/v1/public/vendor-support/open': {
          status: 404,
          body: problem(404, 'support_link_not_usable'),
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('support-start-open'));
    expect((await screen.findByTestId('support-start-failed')).textContent).toContain(
      "This link can't be used",
    );
    expect(screen.getByTestId('support-start-open').closest('button')?.disabled).toBe(true);
    expect(fake.calls.filter((c) => c.path.includes('vendor-support/open'))).toHaveLength(1);
  });
});

describe('the one-time password of a call-back grant', () => {
  it('is kept by no cache once the dialog resets the mutation', async () => {
    const made = {
      id: 'g1',
      one_time_password: PASSWORD,
      engineer_name: 'Omar Engineer',
    } as unknown as SupportGrantMade;
    const fake = fakeApi({
      'POST /api/v1/identity/vendor-support/grants': { status: 201, body: made },
      'GET /api/v1/identity/vendor-support/grants': { body: [] },
    });
    restore = fake.restore;
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useCreateSupportGrant(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({
        key: 'k1',
        body: {
          engineer_name: 'Omar Engineer',
          engineer_email: 'omar@extravis.com',
          reason: 'A workflow is stuck',
          access: 'view',
          unmask_personal: false,
          verification: 'out_of_band',
          confirmation_note: 'Called back',
        },
      });
    });
    act(() => {
      result.current.reset(); // what the dialog's close does
    });
    await waitFor(() => {
      const caches = JSON.stringify([
        client
          .getMutationCache()
          .getAll()
          .map((m) => m.state),
        client
          .getQueryCache()
          .getAll()
          .map((q) => q.state),
      ]);
      expect(caches).not.toContain(PASSWORD);
    });
    expect(storageHolds(PASSWORD)).toBe(false);
  });
});

describe('a vendor support session', () => {
  it('opens the console though it holds no role (the BFF says the same)', () => {
    expect(requesterOnly({ roles: [], user_type: 'vendor_support' })).toBe(false);
    expect(requesterOnly({ roles: [], user_type: 'requester' })).toBe(true);
    expect(requesterOnly({ roles: ['requester'], user_type: 'technician' })).toBe(true);
  });

  it('says so on every page, and labels the names it may not see', async () => {
    const support = fakeSession({ roles: [] });
    const fake = consoleApi({
      me: {
        ...support,
        user: { ...support.user, user_type: 'vendor_support' },
        support: {
          grant_id: '01900000-0000-7000-8000-0000000000aa',
          access: 'view',
          ends_at: '2099-01-01T10:00:00Z',
          contacts_masked: true,
        },
      },
    });
    restore = fake.restore;
    window.history.pushState({}, '', '/');
    render(<App />);
    const banner = await screen.findByTestId('support-banner');
    expect(banner.textContent).toContain("You're signed in as Extravis support");
    expect(banner.textContent).toContain('hidden');
    await waitFor(() => {
      expect(shownName('')).toBe('Person hidden');
    });
    expect(shownName('Aisha')).toBe('Aisha');
  });
});
