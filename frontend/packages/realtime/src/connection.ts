import { Centrifuge, UnauthorizedError, type Subscription } from 'centrifuge';

import { ApiError, fetchConnectionToken, fetchSubscriptionToken } from '@supportx/api-client';

import type { ConnectionStatus, PresenceMember, RealtimeMessage } from './types';

/** Disconnect code the server uses after an access change (backend app/shared/realtime). */
export const ACCESS_CHANGED = 4000;
/** Without a connection for this long, screens fall back to timed refreshes. */
export const FALLBACK_AFTER_MS = 10_000;
export const POLL_INTERVAL_MS = 15_000;

type MessageListener = (message: RealtimeMessage) => void;
type PresenceListener = (members: PresenceMember[]) => void;

interface ChannelEntry {
  subscription: Subscription;
  listeners: Set<MessageListener>;
  presenceListeners: Set<PresenceListener>;
  members: Map<string, PresenceMember>;
  presence: boolean;
  denied: boolean;
}

/** What centrifuge-js needs from us; tests replace it with a fake. */
export type ClientFactory = (getToken: () => Promise<string>) => Centrifuge;

/** WebSocket first; HTTP streaming, then SSE when a proxy blocks WebSockets (§8.3). */
export const defaultClientFactory: ClientFactory = (getToken) => {
  const origin = window.location.origin;
  const ws = origin.replace(/^http/, 'ws');
  return new Centrifuge(
    [
      { transport: 'websocket', endpoint: `${ws}/connection/websocket` },
      { transport: 'http_stream', endpoint: `${origin}/connection/http_stream` },
      { transport: 'sse', endpoint: `${origin}/connection/sse` },
    ],
    {
      getToken,
      emulationEndpoint: `${origin}/emulation`,
      minReconnectDelay: 500,
      maxReconnectDelay: 10_000,
    },
  );
};

let activeFactory: ClientFactory = defaultClientFactory;

/** Replace the client factory app-wide (app test setups use `inertClientFactory`). */
export function setDefaultClientFactory(factory: ClientFactory): void {
  activeFactory = factory;
}

/** A client that never connects: for app-level tests that do not exercise realtime. */
export const inertClientFactory: ClientFactory = () => {
  const subscription = {
    on: () => subscription,
    subscribe: () => undefined,
    unsubscribe: () => undefined,
    presence: () => Promise.resolve({ clients: {} }),
  };
  const client = {
    on: () => client,
    newSubscription: () => subscription,
    getSubscription: () => null,
    removeSubscription: () => undefined,
    connect: () => undefined,
    disconnect: () => undefined,
  };
  return client as unknown as Centrifuge;
};

function denial(error: unknown): never {
  // 401: the session ended; 403: the policy layer said no. Either way stop asking.
  if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
    throw new UnauthorizedError(error.message);
  }
  throw error;
}

function isMessage(data: unknown): data is RealtimeMessage {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as { type?: unknown }).type === 'string' &&
    Array.isArray((data as { ids?: unknown }).ids)
  );
}

/**
 * One realtime connection for one session (tenant + user): the Centrifugo client, the channels
 * screens follow (shared and reference-counted), presence, and the status shown to the user.
 */
export class RealtimeConnection {
  readonly client: Centrifuge;
  private readonly channels = new Map<string, ChannelEntry>();
  private readonly statusListeners = new Set<(status: ConnectionStatus) => void>();
  private readonly reconnectListeners = new Set<(code: number) => void>();
  private status: ConnectionStatus = 'connecting';
  private clientId: string | null = null;
  private fallbackTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private transport: string | null = null;

  constructor(factory: ClientFactory = activeFactory) {
    this.client = factory(() => fetchConnectionToken().catch(denial));
    this.client.on('connecting', (ctx) => {
      this.setStatus(this.status === 'connected' ? 'reconnecting' : this.status);
      this.armFallback();
      for (const listener of this.reconnectListeners) listener(ctx.code);
    });
    this.client.on('connected', (ctx) => {
      const wasPolling = this.status === 'polling';
      this.clientId = ctx.client;
      this.transport = ctx.transport;
      this.clearTimers();
      this.setStatus('connected');
      if (wasPolling) this.refreshAll(); // reconcile what changed while we were polling
    });
    this.client.on('disconnected', () => {
      this.clearTimers();
      this.setStatus('offline');
    });
  }

  connect(): void {
    this.setStatus('connecting');
    this.armFallback();
    this.client.connect();
  }

  close(): void {
    this.clearTimers();
    this.client.disconnect();
    this.channels.clear();
  }

  get currentStatus(): ConnectionStatus {
    return this.status;
  }

  get currentTransport(): string | null {
    return this.transport;
  }

  get ownClientId(): string | null {
    return this.clientId;
  }

  onStatus(listener: (status: ConnectionStatus) => void): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  /** Called with the reason code whenever the connection starts (re)connecting. */
  onReconnect(listener: (code: number) => void): () => void {
    this.reconnectListeners.add(listener);
    return () => this.reconnectListeners.delete(listener);
  }

  /**
   * Follow `channel`: `listener` gets every message. When missed messages cannot be recovered
   * (history too short, long disconnect) it gets a `{type: 'refresh'}` message instead, which
   * screens treat as "refetch what you show" (architecture.md §8.3).
   */
  join(channel: string, listener: MessageListener, presence = false): () => void {
    const entry = this.channels.get(channel) ?? this.open(channel, presence);
    entry.listeners.add(listener);
    return () => {
      entry.listeners.delete(listener);
      if (entry.listeners.size === 0 && entry.presenceListeners.size === 0) this.drop(channel);
    };
  }

  /** Who else follows `channel` (record channels only). */
  watchPresence(channel: string, listener: PresenceListener): () => void {
    const entry = this.channels.get(channel) ?? this.open(channel, true);
    entry.presenceListeners.add(listener);
    listener(this.membersOf(entry));
    return () => {
      entry.presenceListeners.delete(listener);
      if (entry.listeners.size === 0 && entry.presenceListeners.size === 0) this.drop(channel);
    };
  }

  isDenied(channel: string): boolean {
    return this.channels.get(channel)?.denied ?? false;
  }

  private open(channel: string, presence: boolean): ChannelEntry {
    const existing = this.client.getSubscription(channel);
    if (existing !== null) this.client.removeSubscription(existing);
    const subscription = this.client.newSubscription(channel, {
      getToken: (ctx) => fetchSubscriptionToken(ctx.channel).catch(denial),
    });
    const entry: ChannelEntry = {
      subscription,
      listeners: new Set(),
      presenceListeners: new Set(),
      members: new Map(),
      presence,
      denied: false,
    };
    subscription.on('publication', (ctx) => {
      if (isMessage(ctx.data)) this.deliver(entry, ctx.data);
    });
    subscription.on('subscribed', (ctx) => {
      entry.denied = false;
      if (ctx.wasRecovering && !ctx.recovered) this.deliver(entry, { type: 'refresh', ids: [] });
      if (entry.presence) void this.loadPresence(entry);
    });
    subscription.on('unsubscribed', (ctx) => {
      // Code 1 = unauthorized: the API refused the token (permission removed).
      entry.denied = ctx.code === 1;
      entry.members.clear();
      this.notifyPresence(entry);
    });
    subscription.on('join', (ctx) => {
      entry.members.set(ctx.info.client, member(ctx.info.client, ctx.info.connInfo));
      this.notifyPresence(entry);
    });
    subscription.on('leave', (ctx) => {
      entry.members.delete(ctx.info.client);
      this.notifyPresence(entry);
    });
    this.channels.set(channel, entry);
    subscription.subscribe();
    return entry;
  }

  private drop(channel: string): void {
    const entry = this.channels.get(channel);
    if (entry === undefined) return;
    this.channels.delete(channel);
    entry.subscription.unsubscribe();
    this.client.removeSubscription(entry.subscription);
  }

  private deliver(entry: ChannelEntry, message: RealtimeMessage): void {
    for (const listener of entry.listeners) listener(message);
  }

  private async loadPresence(entry: ChannelEntry): Promise<void> {
    try {
      const result = await entry.subscription.presence();
      entry.members = new Map(
        Object.entries(result.clients).map(([id, info]) => [id, member(id, info.connInfo)]),
      );
      this.notifyPresence(entry);
    } catch {
      // presence is a nicety; the record still updates live
    }
  }

  private membersOf(entry: ChannelEntry): PresenceMember[] {
    return [...entry.members.values()].filter((m) => m.clientId !== this.clientId);
  }

  private notifyPresence(entry: ChannelEntry): void {
    const members = this.membersOf(entry);
    for (const listener of entry.presenceListeners) listener(members);
  }

  private setStatus(status: ConnectionStatus): void {
    if (status === this.status) return;
    this.status = status;
    for (const listener of this.statusListeners) listener(status);
  }

  private armFallback(): void {
    if (this.fallbackTimer !== null || this.status === 'polling') return;
    this.fallbackTimer = setTimeout(() => {
      this.fallbackTimer = null;
      if (this.status === 'connected') return;
      this.setStatus('polling');
      this.pollTimer = setInterval(() => {
        this.refreshAll();
      }, POLL_INTERVAL_MS);
    }, FALLBACK_AFTER_MS);
  }

  private clearTimers(): void {
    if (this.fallbackTimer !== null) clearTimeout(this.fallbackTimer);
    if (this.pollTimer !== null) clearInterval(this.pollTimer);
    this.fallbackTimer = null;
    this.pollTimer = null;
  }

  /** Every followed screen refetches (polling fallback, or back from it). */
  private refreshAll(): void {
    for (const entry of this.channels.values()) this.deliver(entry, { type: 'refresh', ids: [] });
  }
}

function member(clientId: string, info: unknown): PresenceMember {
  const data = (info ?? {}) as { user_id?: unknown; name?: unknown };
  return {
    clientId,
    userId: typeof data.user_id === 'string' ? data.user_id : '',
    name: typeof data.name === 'string' ? data.name : '',
  };
}
