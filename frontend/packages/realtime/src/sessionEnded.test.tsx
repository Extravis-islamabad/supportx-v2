import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { Centrifuge } from 'centrifuge';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '@supportx/api-client';
import { fakeApi, problem } from '@supportx/api-client/testing';

import { RETRY_DELAYS_MS, RealtimeConnection, SESSION_ENDED } from './connection';
import { RealtimeProvider } from './RealtimeProvider';

/**
 * An ended session (lane B's condition 6 on #566, the coordinator's conditions): the screens learn
 * it at once (4001, or the connection token refused with 401), and the connection stops. A 403,
 * a network drop or a 5xx is not an ended session: those keep retrying as before.
 */

type Handler = (ctx: never) => void;

class FakeClient {
  handlers = new Map<string, Handler[]>();
  connects = 0;
  disconnects = 0;
  constructor(readonly getToken: () => Promise<string>) {}
  on(event: string, handler: Handler) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
    return this;
  }
  emit(event: string, ctx: unknown) {
    for (const handler of this.handlers.get(event) ?? []) handler(ctx as never);
  }
  newSubscription() {
    return { on: () => undefined, subscribe: () => undefined, unsubscribe: () => undefined };
  }
  getSubscription() {
    return null;
  }
  removeSubscription() {
    return undefined;
  }
  connect() {
    this.connects += 1;
  }
  disconnect() {
    this.disconnects += 1;
  }
}

let client: FakeClient;
const factory = (getToken: () => Promise<string>) => {
  client = new FakeClient(getToken);
  return client as unknown as Centrifuge;
};
const LONGEST_RETRY = Math.max(...RETRY_DELAYS_MS) + 1;

function tokenAnswer(status: number) {
  return fakeApi({
    'POST /api/v1/realtime/connection-token': {
      status,
      body: status < 300 ? { token: 't' } : problem(status, 'refused'),
    },
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe('an ended session', () => {
  it('4001 from the server: the screens are told once and nothing reconnects', () => {
    vi.useFakeTimers();
    const connection = new RealtimeConnection(factory);
    const ended = vi.fn();
    connection.onEnded(ended);
    connection.connect();
    client.emit('connecting', { code: SESSION_ENDED, reason: 'access ended' });
    expect(ended).toHaveBeenCalledTimes(1);
    expect(client.disconnects).toBe(1);
    client.emit('disconnected', { code: 0, reason: 'disconnect called' });
    vi.advanceTimersByTime(LONGEST_RETRY * 3);
    expect(client.connects).toBe(1); // no reconnect loop
    expect(connection.currentStatus).toBe('offline');
    expect(ended).toHaveBeenCalledTimes(1);
  });

  it('once ended, nothing reconnects: not the network coming back, not the tab regaining focus', () => {
    vi.useFakeTimers();
    const connection = new RealtimeConnection(factory);
    connection.connect();
    client.emit('connecting', { code: SESSION_ENDED, reason: 'access ended' });
    client.emit('disconnected', { code: 0, reason: 'disconnect called' });
    window.dispatchEvent(new Event('online'));
    window.dispatchEvent(new Event('focus'));
    document.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(LONGEST_RETRY * 3);
    connection.acquire(); // a screen mounting afterwards
    vi.advanceTimersByTime(LONGEST_RETRY);
    expect(client.connects).toBe(1);
    expect(connection.currentStatus).toBe('offline');
  });

  it('the connection token refused with 401: told once, and it stops', async () => {
    const api = tokenAnswer(401);
    try {
      const connection = new RealtimeConnection(factory);
      const ended = vi.fn();
      connection.onEnded(ended);
      connection.connect();
      await expect(client.getToken()).rejects.toBeDefined();
      vi.useFakeTimers();
      client.emit('disconnected', { code: 1, reason: 'unauthorized' });
      expect(ended).toHaveBeenCalledTimes(1);
      vi.advanceTimersByTime(LONGEST_RETRY * 3);
      expect(client.connects).toBe(1);
    } finally {
      api.restore();
    }
  });

  it.each([
    ['a 403 (no permission)', 403, { code: 1, reason: 'unauthorized' }],
    ['a 5xx', 503, { code: 1, reason: 'unauthorized' }],
    ['a network drop', 200, { code: 2, reason: 'bad protocol' }],
  ])('%s is not an ended session: nobody is told, and it retries', async (_, status, ctx) => {
    const api = tokenAnswer(status);
    try {
      const connection = new RealtimeConnection(factory);
      const ended = vi.fn();
      connection.onEnded(ended);
      connection.connect();
      await client.getToken().catch(() => undefined);
      vi.useFakeTimers();
      client.emit('disconnected', ctx);
      vi.advanceTimersByTime(LONGEST_RETRY);
      expect(ended).not.toHaveBeenCalled();
      expect(client.connects).toBe(2); // tried again
    } finally {
      api.restore();
    }
  });

  it('the provider asks for the session again, so the app signs out', () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    function wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={queryClient}>
          <RealtimeProvider tenantId="tenant-1" userId="user-1" factory={factory}>
            {children}
          </RealtimeProvider>
        </QueryClientProvider>
      );
    }
    render(<div />, { wrapper });
    invalidate.mockClear();
    client.emit('connecting', { code: SESSION_ENDED, reason: 'access ended' });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.session });
  });
});
