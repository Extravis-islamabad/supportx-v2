import { QueryClient, QueryObserver } from '@tanstack/react-query';
import type { Centrifuge } from 'centrifuge';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { RealtimeConnection } from './connection';
import { refreshList, refreshQueries } from './hooks';
import type { RealtimeMessage } from './types';

/**
 * architecture.md §8.3, the first-subscribe catch-up (vendor-support.spec:105): a screen fetched
 * its list, a change was published, and only then did its subscription go live, so the change
 * was never shown. The first `subscribed` now fetches each active query once more (a first fetch
 * still in flight, once it lands), and nothing for data that only arrived after going live.
 */

type Handler = (ctx: never) => void;

class FakeSubscription {
  handlers = new Map<string, Handler[]>();
  on(event: string, handler: Handler) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
    return this;
  }
  emit(event: string, ctx: unknown) {
    for (const handler of this.handlers.get(event) ?? []) handler(ctx as never);
  }
  subscribe() {
    return undefined;
  }
  unsubscribe() {
    return undefined;
  }
}

class FakeClient {
  subscriptions = new Map<string, FakeSubscription>();
  on() {
    return this;
  }
  newSubscription(channel: string) {
    const subscription = new FakeSubscription();
    this.subscriptions.set(channel, subscription);
    return subscription;
  }
  getSubscription() {
    return null;
  }
  removeSubscription() {
    return undefined;
  }
  connect() {
    return undefined;
  }
  disconnect() {
    return undefined;
  }
}

const CHANNEL = 't:tenant-1:list:grants';
const KEY = ['grants'];

function setUp() {
  const client = new FakeClient();
  const connection = new RealtimeConnection(() => client as unknown as Centrifuge);
  const queryClient = new QueryClient();
  const fetches = vi.fn(() => Promise.resolve(['grant']));
  const heard: RealtimeMessage[] = [];
  connection.join(CHANNEL, (message) => {
    heard.push(message);
    if (message.type === 'refresh') refreshList(queryClient, KEY);
  });
  const subscription = client.subscriptions.get(CHANNEL);
  if (subscription === undefined) throw new Error('no subscription');
  /** The screen mounting: an active observer, whose subscribe is the screen's first fetch. */
  const mount = () =>
    new QueryObserver(queryClient, {
      queryKey: KEY,
      queryFn: fetches,
      staleTime: Infinity,
    }).subscribe(() => undefined);
  /** The screen's data has arrived (the fetch settled, not merely started). */
  const settled = () =>
    vi.waitFor(() => {
      expect(queryClient.getQueryState(KEY)?.status).toBe('success');
      expect(queryClient.getQueryState(KEY)?.fetchStatus).toBe('idle');
    });
  return { fetches, heard, subscription, mount, settled };
}

const LIVE = { wasRecovering: false, recovered: false };

afterEach(() => {
  vi.useRealTimers();
});

describe('the first-subscribe catch-up', () => {
  it('a change between the fetch and going live is fetched once the channel is live', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(1_000);
    const { fetches, heard, subscription, mount, settled } = setUp();
    const unmount = mount(); // the screen's first fetch
    await settled();
    vi.setSystemTime(1_900); // ...a change is published to nobody, then the channel goes live
    subscription.emit('subscribed', LIVE);
    expect(heard).toEqual([{ type: 'refresh', ids: [], catchUp: true }]);
    await vi.waitFor(() => {
      expect(fetches).toHaveBeenCalledTimes(2); // exactly one catch-up refetch
    });
    unmount();
  });

  it('data that arrived after the channel went live is not fetched again', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(1_000);
    const { fetches, subscription, mount, settled } = setUp();
    subscription.emit('subscribed', LIVE); // live first, before the screen has data
    vi.setSystemTime(1_500);
    const unmount = mount(); // then its first fetch
    await settled();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetches).toHaveBeenCalledTimes(1); // nothing extra
    unmount();
  });

  it('a first fetch still in flight when the channel goes live is fetched once more after it lands', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(1_000);
    const { fetches, subscription, mount } = setUp();
    let finish: (value: string[]) => void = () => undefined;
    fetches.mockImplementationOnce(
      () =>
        new Promise<string[]>((resolve) => {
          finish = resolve;
        }),
    );
    const unmount = mount(); // its first fetch, still in flight
    vi.setSystemTime(1_900);
    subscription.emit('subscribed', LIVE);
    // Its server read may predate the change that went to nobody (lane B's #602 review): once it
    // lands, it is fetched once more, and only once.
    finish(['grant']);
    await vi.waitFor(() => {
      expect(fetches).toHaveBeenCalledTimes(2);
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetches).toHaveBeenCalledTimes(2);
    unmount();
  });

  it('a later re-subscribe that recovered everything is no catch-up', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(1_000);
    const { fetches, heard, subscription, mount, settled } = setUp();
    const unmount = mount();
    await settled();
    vi.setSystemTime(1_900);
    subscription.emit('subscribed', LIVE); // the first time: the catch-up
    await vi.waitFor(() => {
      expect(fetches).toHaveBeenCalledTimes(2);
    });
    vi.setSystemTime(5_000);
    subscription.emit('subscribed', { wasRecovering: true, recovered: true }); // nothing missed
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(heard).toHaveLength(1);
    expect(fetches).toHaveBeenCalledTimes(2);
    unmount();
  });
});

describe('refreshQueries, for handlers that refresh a key directly', () => {
  it('gives a direct handler the same catch-up, a first fetch in flight included', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(1_000);
    const client = new FakeClient();
    const connection = new RealtimeConnection(() => client as unknown as Centrifuge);
    const queryClient = new QueryClient();
    const fetches = vi.fn(() => Promise.resolve(['request']));
    let finish: (value: string[]) => void = () => undefined;
    fetches.mockImplementationOnce(
      () =>
        new Promise<string[]>((resolve) => {
          finish = resolve;
        }),
    );
    // A handler like the request pages': it refreshes its key whatever the message says.
    connection.join(CHANNEL, () => {
      refreshQueries(queryClient, ['requests']);
    });
    const unmount = new QueryObserver(queryClient, {
      queryKey: ['requests'],
      queryFn: fetches,
      staleTime: Infinity,
    }).subscribe(() => undefined);
    vi.setSystemTime(1_900);
    client.subscriptions.get(CHANNEL)?.emit('subscribed', LIVE);
    finish(['request']);
    await vi.waitFor(() => {
      expect(fetches).toHaveBeenCalledTimes(2);
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetches).toHaveBeenCalledTimes(2);
    unmount();
  });
});
