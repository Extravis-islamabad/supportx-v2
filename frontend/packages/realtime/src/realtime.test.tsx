import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook, waitFor } from '@testing-library/react';
import { UnauthorizedError, type Centrifuge } from 'centrifuge';
import { StrictMode, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '@supportx/api-client';
import { fakeApi, problem } from '@supportx/api-client/testing';

import {
  FALLBACK_AFTER_MS,
  POLL_INTERVAL_MS,
  RETRY_DELAYS_MS,
  RealtimeConnection,
} from './connection';
import { refreshRecord, useListChannel, useRealtimeStatus, useRecordChannel } from './hooks';
import { RealtimeProvider } from './RealtimeProvider';
import type { RealtimeMessage } from './types';

type Handler = (ctx: never) => void;

/** Just enough of centrifuge-js: events can be fired from the test. */
class FakeEmitter {
  handlers = new Map<string, Handler[]>();
  on(event: string, handler: Handler) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
    return this;
  }
  emit(event: string, ctx: unknown) {
    for (const handler of this.handlers.get(event) ?? []) handler(ctx as never);
  }
}

class FakeSubscription extends FakeEmitter {
  subscribed = false;
  subscribeCalls = 0;
  constructor(
    readonly channel: string,
    readonly options: { getToken: (ctx: { channel: string }) => Promise<string> },
    readonly clients: Record<string, { client: string; connInfo: unknown }> = {},
  ) {
    super();
  }
  subscribe() {
    this.subscribed = true;
    this.subscribeCalls += 1;
  }
  unsubscribe() {
    this.subscribed = false;
  }
  presence() {
    return Promise.resolve({ clients: this.clients });
  }
}

class FakeClient extends FakeEmitter {
  subs = new Map<string, FakeSubscription>();
  connected = false;
  connects = 0;
  disconnects = 0;
  presence: Record<string, { client: string; connInfo: unknown }> = {};
  constructor(readonly getToken: () => Promise<string>) {
    super();
  }
  newSubscription(channel: string, options: FakeSubscription['options']) {
    const sub = new FakeSubscription(channel, options, this.presence);
    this.subs.set(channel, sub);
    return sub;
  }
  getSubscription(channel: string) {
    return this.subs.get(channel) ?? null;
  }
  removeSubscription(sub: FakeSubscription | null) {
    if (sub !== null) this.subs.delete(sub.channel);
  }
  connect() {
    this.connected = true;
    this.connects += 1;
  }
  disconnect() {
    this.connected = false;
    this.disconnects += 1;
  }
  publish(channel: string, data: RealtimeMessage) {
    this.subs.get(channel)?.emit('publication', { channel, data });
  }
}

let client: FakeClient;
const factory = (getToken: () => Promise<string>) => {
  client = new FakeClient(getToken);
  return client as unknown as Centrifuge;
};

const T = 'tenant-1';
const U = 'user-1';

afterEach(() => {
  vi.useRealTimers();
});

describe('RealtimeConnection', () => {
  it('shares one subscription per channel and drops it with the last listener', () => {
    const connection = new RealtimeConnection(factory);
    const a = vi.fn();
    const b = vi.fn();
    const leaveA = connection.join('t:x:queue:users', a);
    const leaveB = connection.join('t:x:queue:users', b);
    expect(client.subs.size).toBe(1);
    client.publish('t:x:queue:users', { type: 'users.changed', ids: ['1'] });
    expect(a).toHaveBeenCalledWith({ type: 'users.changed', ids: ['1'] });
    expect(b).toHaveBeenCalledTimes(1);
    leaveA();
    expect(client.subs.size).toBe(1);
    leaveB();
    expect(client.subs.size).toBe(0);
  });

  it('ignores publications that are not realtime messages', () => {
    const connection = new RealtimeConnection(factory);
    const listener = vi.fn();
    connection.join('t:x:queue:users', listener);
    client.subs.get('t:x:queue:users')?.emit('publication', { data: 'nope' });
    expect(listener).not.toHaveBeenCalled();
  });

  it('turns an unrecoverable gap into a refresh', () => {
    const connection = new RealtimeConnection(factory);
    const listener = vi.fn();
    connection.join('t:x:queue:users', listener);
    const sub = client.subs.get('t:x:queue:users');
    sub?.emit('subscribed', { wasRecovering: true, recovered: true });
    expect(listener).not.toHaveBeenCalled();
    sub?.emit('subscribed', { wasRecovering: true, recovered: false });
    expect(listener).toHaveBeenCalledWith({ type: 'refresh', ids: [] });
  });

  it('refuses tokens the API refuses (session ended or permission removed)', async () => {
    const api = fakeApi({
      'POST /api/v1/realtime/connection-token': {
        status: 401,
        body: problem(401, 'unauthenticated'),
      },
      'POST /api/v1/realtime/subscription-token': {
        status: 403,
        body: problem(403, 'realtime_channel_denied'),
      },
    });
    try {
      const connection = new RealtimeConnection(factory);
      await expect(client.getToken()).rejects.toBeInstanceOf(UnauthorizedError);
      connection.join('t:x:users:1', vi.fn());
      const sub = client.subs.get('t:x:users:1');
      await expect(sub?.options.getToken({ channel: 't:x:users:1' })).rejects.toBeInstanceOf(
        UnauthorizedError,
      );
      sub?.emit('unsubscribed', { code: 1, reason: 'unauthorized' });
      expect(connection.isDenied('t:x:users:1')).toBe(true);
    } finally {
      api.restore();
    }
  });

  it('falls back to timed refreshes without a connection, and reconciles once back', () => {
    vi.useFakeTimers();
    const connection = new RealtimeConnection(factory);
    const listener = vi.fn();
    const statuses: string[] = [];
    connection.onStatus((s) => statuses.push(s));
    connection.join('t:x:queue:users', listener);
    connection.connect();
    vi.advanceTimersByTime(FALLBACK_AFTER_MS);
    expect(connection.currentStatus).toBe('polling');
    vi.advanceTimersByTime(POLL_INTERVAL_MS * 2);
    expect(listener).toHaveBeenCalledTimes(2);
    client.emit('connected', { client: 'c1', transport: 'sse' });
    expect(connection.currentStatus).toBe('connected');
    expect(connection.currentTransport).toBe('sse');
    expect(listener).toHaveBeenCalledTimes(3); // the reconcile refresh
    client.emit('connecting', { code: 4000, reason: 'access changed' });
    expect(statuses).toEqual(['polling', 'connected', 'reconnecting']);
  });

  it('tracks presence without counting this connection', async () => {
    const connection = new RealtimeConnection(factory);
    client.presence = {
      me: { client: 'me', connInfo: { user_id: U, name: 'Me' } },
      other: { client: 'other', connInfo: { user_id: 'u2', name: 'Bilal' } },
    };
    client.emit('connected', { client: 'me', transport: 'websocket' });
    const seen: string[][] = [];
    connection.join('t:x:users:1', vi.fn(), true);
    connection.watchPresence('t:x:users:1', (members) => seen.push(members.map((m) => m.name)));
    const sub = client.subs.get('t:x:users:1');
    sub?.emit('subscribed', { wasRecovering: false, recovered: false });
    await waitFor(() => {
      expect(seen.at(-1)).toEqual(['Bilal']);
    });
    sub?.emit('join', { info: { client: 'c3', connInfo: { user_id: 'u3', name: 'Chen' } } });
    expect(seen.at(-1)).toEqual(['Bilal', 'Chen']);
    sub?.emit('leave', { info: { client: 'other' } });
    expect(seen.at(-1)).toEqual(['Chen']);
  });
});

describe('RealtimeProvider and hooks', () => {
  let queryClient: QueryClient;
  let api: ReturnType<typeof fakeApi>;

  beforeEach(() => {
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    api = fakeApi({
      'GET /api/v1/realtime/lists/users': { body: { channels: [`t:${T}:queue:users`] } },
    });
  });
  afterEach(() => {
    api.restore();
  });

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <RealtimeProvider tenantId={T} userId={U} factory={factory}>
          {children}
        </RealtimeProvider>
      </QueryClientProvider>
    );
  }

  it('follows the own and tenant channels; access changes refresh the session', () => {
    queryClient.setQueryData(queryKeys.session, { stale: false });
    queryClient.setQueryData(queryKeys.entitlements, { stale: false });
    render(<div />, { wrapper });
    expect(client.connected).toBe(true);
    expect([...client.subs.keys()].sort()).toEqual([`t:${T}:broadcast`, `t:${T}:user:${U}`]);
    act(() => {
      client.publish(`t:${T}:user:${U}`, { type: 'access.changed', ids: [U] });
    });
    expect(queryClient.getQueryState(queryKeys.session)?.isInvalidated).toBe(true);
    queryClient.setQueryData(queryKeys.entitlements, { stale: false });
    act(() => {
      client.publish(`t:${T}:broadcast`, { type: 'entitlements.changed', ids: [] });
    });
    expect(queryClient.getQueryState(queryKeys.entitlements)?.isInvalidated).toBe(true);
  });

  it('BUG-13: leaving or reloading the page disconnects at once (no ghost viewer)', () => {
    render(<div />, { wrapper });
    expect(client.connected).toBe(true);
    act(() => {
      window.dispatchEvent(new Event('pagehide'));
    });
    expect(client.connected).toBe(false);
  });

  it('an access-changed disconnect refreshes the session too', () => {
    queryClient.setQueryData(queryKeys.session, { stale: false });
    render(<div />, { wrapper });
    act(() => {
      client.emit('connecting', { code: 4000, reason: 'access changed' });
    });
    expect(queryClient.getQueryState(queryKeys.session)?.isInvalidated).toBe(true);
  });

  it('a list follows the channels the API names', async () => {
    const seen: RealtimeMessage[] = [];
    renderHook(
      () => {
        useListChannel('users', (m) => seen.push(m));
      },
      { wrapper },
    );
    await waitFor(() => {
      expect(client.subs.has(`t:${T}:queue:users`)).toBe(true);
    });
    client.publish(`t:${T}:queue:users`, { type: 'users.changed', ids: ['9'] });
    expect(seen).toEqual([{ type: 'users.changed', ids: ['9'] }]);
  });

  it('a record channel is joined with presence and reports other viewers', async () => {
    client = undefined as unknown as FakeClient;
    const { result } = renderHook(() => useRecordChannel('users', 'u9', () => undefined), {
      wrapper,
    });
    const sub = client.subs.get(`t:${T}:users:u9`);
    expect(sub?.subscribed).toBe(true);
    act(() => {
      sub?.emit('join', { info: { client: 'c2', connInfo: { user_id: 'u2', name: 'Bilal' } } });
    });
    await waitFor(() => {
      expect(result.current.map((m) => m.name)).toEqual(['Bilal']);
    });
  });

  it('status is offline outside a session', () => {
    const { result } = renderHook(() => useRealtimeStatus(), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={queryClient}>
          <RealtimeProvider factory={factory}>{children}</RealtimeProvider>
        </QueryClientProvider>
      ),
    });
    expect(result.current).toBe('offline');
  });
});

describe('refreshRecord', () => {
  it('skips a refetch when the cached copy is already at that version', () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(['users', 'detail', '1'], { version: 5 });
    refreshRecord(queryClient, ['users', 'detail', '1'], {
      type: 'users.changed',
      ids: ['1'],
      version: 5,
    });
    expect(queryClient.getQueryState(['users', 'detail', '1'])?.isInvalidated).toBe(false);
    refreshRecord(queryClient, ['users', 'detail', '1'], {
      type: 'users.changed',
      ids: ['1'],
      version: 6,
    });
    expect(queryClient.getQueryState(['users', 'detail', '1'])?.isInvalidated).toBe(true);
  });
});

describe('WP-020b QA: one connection per tab, never silently dead', () => {
  const clients: FakeClient[] = [];
  const counting = (getToken: () => Promise<string>) => {
    const made = factory(getToken);
    clients.push(client);
    return made;
  };
  let queryClient: QueryClient;
  beforeEach(() => {
    clients.length = 0;
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  });

  function Viewer({ onMessage }: { onMessage: (m: RealtimeMessage) => void }) {
    useRecordChannel('wi', 'r1', onMessage);
    return null;
  }

  function app(strict: boolean, onMessage: (m: RealtimeMessage) => void) {
    const tree = (
      <QueryClientProvider client={queryClient}>
        <RealtimeProvider tenantId={T} userId={U} factory={counting}>
          <Viewer onMessage={onMessage} />
        </RealtimeProvider>
      </QueryClientProvider>
    );
    return strict ? <StrictMode>{tree}</StrictMode> : tree;
  }

  for (const strict of [true, false]) {
    it(`BUG-02: exactly one live connection and a live record channel (${strict ? 'development, StrictMode' : 'production'})`, async () => {
      vi.useFakeTimers();
      const seen: RealtimeMessage[] = [];
      render(app(strict, (m) => seen.push(m)));
      await act(async () => {
        await vi.runOnlyPendingTimersAsync();
      });
      const connected = clients.filter((c) => c.connected);
      expect(connected).toHaveLength(1);
      expect(clients.filter((c) => c.connects > 0)).toHaveLength(1);
      expect(connected[0]?.connects).toBe(1);
      expect(connected[0]?.disconnects).toBe(0);
      const sub = connected[0]?.subs.get(`t:${T}:wi:r1`);
      expect(sub?.subscribed).toBe(true);
      act(() => {
        connected[0]?.publish(`t:${T}:wi:r1`, { type: 'work_items.changed', ids: ['r1'] });
      });
      expect(seen).toEqual([{ type: 'work_items.changed', ids: ['r1'] }]);
    });
  }

  it('BUG-02: a connection that drops while screens use it is shown and retried', () => {
    vi.useFakeTimers();
    const connection = new RealtimeConnection(factory);
    connection.acquire();
    expect(client.connects).toBe(1);
    // The connection token was refused (or the server ended the connection for good).
    client.emit('disconnected', { code: 3500, reason: 'unauthorized' });
    expect(connection.currentStatus).toBe('reconnecting'); // shown, never silently offline
    vi.advanceTimersByTime(RETRY_DELAYS_MS[0]);
    expect(client.connects).toBe(2);
    client.emit('connected', { client: 'c2', transport: 'websocket' });
    expect(connection.currentStatus).toBe('connected');
    // Closing on purpose (sign out, leaving) is not a drop: no retry.
    connection.close();
    client.emit('disconnected', { code: 0, reason: 'disconnect called' });
    vi.advanceTimersByTime(60_000);
    expect(client.connects).toBe(2);
    expect(connection.currentStatus).toBe('offline');
  });

  it('BUG-02: a refused or ended channel is shown and retried, then catches up', () => {
    vi.useFakeTimers();
    const connection = new RealtimeConnection(factory);
    const listener = vi.fn();
    connection.join('t:x:wi:1', listener);
    connection.connect();
    client.emit('connected', { client: 'c1', transport: 'websocket' });
    const sub = client.subs.get('t:x:wi:1');
    sub?.emit('subscribed', { wasRecovering: false, recovered: false });
    expect(connection.currentStatus).toBe('connected');
    // The API refused the token (e.g. its access cache was still stale after a change).
    sub?.emit('unsubscribed', { code: 1, reason: 'unauthorized' });
    expect(connection.currentStatus).toBe('limited');
    const before = sub?.subscribeCalls ?? 0;
    vi.advanceTimersByTime(RETRY_DELAYS_MS[0]);
    expect(sub?.subscribeCalls).toBe(before + 1);
    sub?.emit('subscribed', { wasRecovering: false, recovered: false });
    expect(connection.currentStatus).toBe('connected');
    expect(listener).toHaveBeenCalledWith({ type: 'refresh', ids: [] }); // fetch what was missed
    // Leaving the screen stops the retries.
    sub?.emit('unsubscribed', { code: 2500, reason: 'server' });
    expect(connection.currentStatus).toBe('limited');
  });
});
