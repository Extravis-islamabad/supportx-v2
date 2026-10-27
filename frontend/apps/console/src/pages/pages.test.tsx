import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { App } from '../App';
import { consoleApi, fakeEntitlements, fakeSession, fakeUser, ME_PATH, problem } from '../test/api';

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

/** IntersectionObserver stand-in: `scrollToEnd()` reports the sentinel as visible. */
const observers: IntersectionObserverCallback[] = [];
class FakeObserver {
  constructor(callback: IntersectionObserverCallback) {
    observers.push(callback);
  }
  observe(): void {
    // the test triggers the callback itself (scrollToEnd)
  }
  disconnect(): void {
    // nothing to release
  }
}
function scrollToEnd() {
  const last = observers.at(-1);
  last?.([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver);
}

describe('My profile', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/profile');
  });
  afterEach(() => {
    restore();
  });

  it('saves with If-Match for the version it loaded', async () => {
    const fake = api({
      routes: {
        [`PATCH ${ME_PATH}`]: {
          body: fakeUser({ signature: 'Regards', version: 4 }),
          headers: { ETag: '"4"' },
        },
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('profile-signature'), {
      target: { value: 'Regards' },
    });
    fireEvent.click(screen.getByTestId('profile-save'));
    expect(await screen.findByText('Your preferences were saved.')).toBeDefined();
    const [patch] = fake.find('PATCH', ME_PATH);
    expect(patch?.headers.get('If-Match')).toBe('"3"');
    expect(patch?.body).toEqual({ signature: 'Regards' }); // only what changed
  });

  it('shows the API field errors inline under the field, translated', async () => {
    api({
      routes: {
        [`PATCH ${ME_PATH}`]: {
          status: 422,
          body: problem(422, 'validation_failed', {
            errors: [
              {
                field: 'body.time_zone',
                code: 'invalid_choice',
                message_key: 'errors.field.invalid_choice',
                params: {},
              },
            ],
          }),
        },
      },
    });
    render(<App />);
    fireEvent.change(await screen.findByTestId('profile-time-zone'), {
      target: { value: 'Mars/Base' },
    });
    fireEvent.click(screen.getByTestId('profile-save'));
    expect((await screen.findByTestId('error-time_zone')).textContent).toBe(
      'This is not one of the allowed values.',
    );
    expect(screen.queryByText(/invalid_choice/)).toBeNull();
  });

  it('on a 409 conflict, "keep my changes" saves again on top of the latest version', async () => {
    let attempt = 0;
    let serverVersion = 3;
    const fake = api({
      routes: {
        [`GET ${ME_PATH}`]: () => ({
          body: fakeUser({ version: serverVersion, signature: 'theirs' }),
          headers: { ETag: `"${String(serverVersion)}"` },
        }),
        [`PATCH ${ME_PATH}`]: () => {
          attempt += 1;
          return attempt === 1
            ? {
                status: 409,
                body: problem(409, 'version_conflict', {
                  params: { expected_version: 3, current_version: 5 },
                }),
              }
            : { body: fakeUser({ version: 6, signature: 'mine' }) };
        },
      },
    });
    render(<App />);
    const signature = await screen.findByTestId('profile-signature');
    serverVersion = 5; // someone else saved meanwhile
    fireEvent.change(signature, { target: { value: 'mine' } });
    fireEvent.click(screen.getByTestId('profile-save'));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Someone else changed this')).toBeDefined();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep my changes' }));
    expect(await screen.findByText('Your preferences were saved.')).toBeDefined();
    const patches = fake.find('PATCH', ME_PATH);
    expect(patches.map((p) => p.headers.get('If-Match'))).toEqual(['"3"', '"5"']);
    expect(patches[1]?.body).toEqual({ signature: 'mine' });
  });

  it('on a 409 conflict, "reload their version" replaces my edits', async () => {
    let serverVersion = 3;
    api({
      routes: {
        [`GET ${ME_PATH}`]: () => ({
          body: fakeUser({
            version: serverVersion,
            signature: serverVersion === 3 ? '' : 'theirs',
          }),
        }),
        [`PATCH ${ME_PATH}`]: { status: 409, body: problem(409, 'version_conflict') },
      },
    });
    render(<App />);
    const signature = await screen.findByTestId('profile-signature');
    serverVersion = 5;
    fireEvent.change(signature, { target: { value: 'mine' } });
    fireEvent.click(screen.getByTestId('profile-save'));
    fireEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', {
        name: 'Reload their version',
      }),
    );
    await waitFor(() => {
      expect(screen.getByTestId<HTMLTextAreaElement>('profile-signature').value).toBe('theirs');
    });
  });

  it('read-only mode: banner for everyone and the Save button disabled', async () => {
    api({
      routes: {
        'GET /api/v1/entitlements': {
          body: fakeEntitlements({ state: 'read_only', state_reason: 'expired', writable: false }),
        },
      },
    });
    render(<App />);
    expect(await screen.findByTestId('read-only-banner')).toBeDefined();
    await waitFor(() => {
      expect(screen.getByTestId('profile-save').hasAttribute('disabled')).toBe(true);
    });
  });

  it('grace: the admin banner shows the days left', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/entitlements': {
          body: fakeEntitlements({
            state: 'grace',
            state_reason: 'expired',
            days_left: 11,
            admin_warning: true,
          }),
        },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('grace-banner')).textContent).toContain('11 days left');
  });
});

describe('Admin › Users', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/admin/users');
    observers.length = 0;
    globalThis.IntersectionObserver = FakeObserver as unknown as typeof IntersectionObserver;
  });
  afterEach(() => {
    restore();
  });

  it('lists, filters by type and loads the next page on scroll', async () => {
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/users': (call) =>
          call.url.searchParams.get('cursor') === null
            ? {
                body: {
                  items: [fakeUser({ id: 'u1', display_name: 'Aisha Tech' })],
                  has_more: true,
                  next_cursor: 'next',
                  estimated_total: 2,
                },
              }
            : {
                body: {
                  items: [
                    fakeUser({
                      id: 'u2',
                      display_name: 'Bilal Requester',
                      user_type: 'requester',
                      last_login_at: null,
                    }),
                  ],
                  has_more: false,
                  next_cursor: null,
                },
              },
      },
    });
    render(<App />);
    expect(await screen.findByText('Aisha Tech')).toBeDefined();
    expect(screen.getByTestId('users-total').textContent).toBe('2 people');
    scrollToEnd();
    expect(await screen.findByText('Bilal Requester')).toBeDefined();
    expect(screen.getByText('Requester')).toBeDefined(); // the label, never the code
    expect(screen.getByText('Never')).toBeDefined();
    expect(await screen.findByTestId('users-end')).toBeDefined();

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search by name or email' }), {
      target: { value: 'ais' },
    });
    // The server's people search (WP-027): word starts, Arabic and Urdu spellings, typos.
    await waitFor(() => {
      const last = fake.find('GET', '/api/v1/users').at(-1);
      expect(last?.url.searchParams.get('q')).toBe('ais');
    });
  });

  it('a failed list shows a translated toast with the reference', async () => {
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/users': {
          status: 500,
          body: problem(500, 'internal_error', { request_id: 'req-500' }),
        },
      },
    });
    render(<App />);
    expect(
      await screen.findByText('Something went wrong on our side. Please try again.'),
    ).toBeDefined();
    expect(
      screen.getByRole('button', { name: /Copy reference/ }).getAttribute('data-reference'),
    ).toBe('req-500');
  });

  it('is not available to requesters (no users.view)', async () => {
    api({ me: fakeSession({ roles: ['requester'], user_type: 'requester' }) });
    render(<App />);
    expect(await screen.findByText(/Ask your administrator for access/)).toBeDefined();
  });
});
