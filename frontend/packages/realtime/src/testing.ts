/**
 * Test helpers (import from '@supportx/realtime/testing'): a scripted Centrifugo client for app
 * tests that need live messages. Never imported by app code.
 */
import type { Centrifuge } from 'centrifuge';

import type { ClientFactory } from './connection';
import type { RealtimeMessage } from './types';

type Handler = (ctx: unknown) => void;

class Emitter {
  private handlers = new Map<string, Handler[]>();
  on(event: string, handler: Handler): this {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
    return this;
  }
  emit(event: string, ctx: unknown): void {
    for (const handler of this.handlers.get(event) ?? []) handler(ctx);
  }
}

class ScriptedSubscription extends Emitter {
  constructor(readonly channel: string) {
    super();
  }
  subscribe(): void {
    this.emit('subscribed', { wasRecovering: false, recovered: false });
  }
  unsubscribe(): void {
    // nothing to tell the server
  }
  presence(): Promise<{ clients: Record<string, never> }> {
    return Promise.resolve({ clients: {} });
  }
}

/** A client whose channels the test can publish to. Install with `setDefaultClientFactory`. */
export function scriptedRealtime() {
  const subscriptions = new Map<string, ScriptedSubscription>();
  const factory: ClientFactory = () => {
    const client = new Emitter() as Emitter & Record<string, unknown>;
    Object.assign(client, {
      newSubscription: (channel: string) => {
        const subscription = new ScriptedSubscription(channel);
        subscriptions.set(channel, subscription);
        return subscription;
      },
      getSubscription: (channel: string) => subscriptions.get(channel) ?? null,
      removeSubscription: (subscription: ScriptedSubscription | null) => {
        if (subscription !== null) subscriptions.delete(subscription.channel);
      },
      connect: () => {
        client.emit('connected', { client: 'test-client', transport: 'websocket' });
      },
      disconnect: () => undefined,
    });
    return client as unknown as Centrifuge;
  };
  return {
    factory,
    /** Channels followed right now (their full names). */
    channels: () => [...subscriptions.keys()],
    /** Deliver a message on every followed channel whose name ends with `suffix`. */
    publish: (suffix: string, message: RealtimeMessage) => {
      for (const [name, subscription] of subscriptions) {
        if (name.endsWith(suffix)) subscription.emit('publication', { data: message });
      }
    },
  };
}
