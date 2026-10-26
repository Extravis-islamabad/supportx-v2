import { Centrifuge, UnauthorizedError, type Subscription } from 'centrifuge';

import { ApiError, fetchConnectionToken, fetchSubscriptionToken } from '@supportx/api-client';

import type { ConnectionStatus, PresenceMember, RealtimeMessage } from './types';

/** Disconnect code the server uses after an access change (backend app/shared/realtime). */
export const ACCESS_CHANGED = 4000;
/** Without a connection for this long, screens fall back to timed refreshes. */
export const FALLBACK_AFTER_MS = 10_000;
export const POLL_INTERVAL_MS = 15_000;
/** A followed channel that was refused or ended is tried again after these delays (then every last one). */
export const RETRY_DELAYS_MS = [2_000, 5_000, 10_000, 30_000] as const;

type MessageListener = (message: RealtimeMessage) => void;
type PresenceListener = (members: PresenceMember[]) => void;

interface ChannelEntry {
  subscription: Subscription;
  listeners: Set<MessageListener>;
  presenceListeners: Set<PresenceListener>;
  members: Map<string, PresenceMember>;
  presence: boolean;
  denied: boolean;
  /** Not subscribed although a screen follows it: refused, or ended by the server. */
  lost: boolean;
  retries: number;
  retryTimer: ReturnType<typeof setTimeout> | null;
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
  // One connection per tab (QA BUG-02): screens acquire and release it; the last release closes it
  // on the next tick, so React StrictMode's unmount-and-remount in development reuses the live
  // connection instead of closing it and opening a second one.
  private holders = 0;
  private started = false;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnects = 0;

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
      this.reconnects = 0;
      this.setStatus(this.anyLost() ? 'limited' : 'connected');
      if (wasPolling) this.refreshAll(); // reconcile what changed while we were polling
    });
    this.client.on('disconnected', () => {
      this.clearTimers();
      // Dropped while screens still use it (token refused, server ended it): show "reconnecting"
      // and try again with backoff, never silently offline (QA BUG-02). Closed on purpose: offline.
      if (this.started) {
        this.setStatus('reconnecting');
        this.scheduleReconnect();
      } else {
        this.setStatus('offline');
      }
    });
  }

  connect(): void {
    this.started = true;
    this.setStatus('connecting');
    this.armFallback();
    this.client.connect();
  }

  /** A screen starts using the connection: connects once, cancels a pending close. */
  acquire(): void {
    this.holders += 1;
    if (this.closeTimer !== null) clearTimeout(this.closeTimer);
    this.closeTimer = null;
    if (!this.started) this.connect();
  }

  /** A screen stops using it; the last one closes it on the next tick unless someone re-acquires. */
  release(): void {
    this.holders = Math.max(0, this.holders - 1);
    if (this.holders > 0 || this.closeTimer !== null) return;
    this.closeTimer = setTimeout(() => {
      this.closeTimer = null;
      if (this.holders === 0) this.close();
    }, 0);
  }

  close(): void {
    this.clearTimers();
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.closeTimer !== null) clearTimeout(this.closeTimer);
    this.closeTimer = null;
    for (const entry of this.channels.values()) this.stopRetry(entry);
    this.started = false;
    this.channels.clear(); // first: the disconnect's unsubscribe events must not schedule retries
    this.client.disconnect();
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
      lost: false,
      retries: 0,
      retryTimer: null,
    };
    subscription.on('publication', (ctx) => {
      if (isMessage(ctx.data)) this.deliver(entry, ctx.data);
    });
    subscription.on('subscribed', (ctx) => {
      entry.denied = false;
      const wasLost = entry.lost;
      this.stopRetry(entry);
      if ((ctx.wasRecovering && !ctx.recovered) || wasLost) {
        this.deliver(entry, { type: 'refresh', ids: [] }); // fetch what was missed meanwhile
      }
      if (entry.presence) void this.loadPresence(entry);
      if (wasLost && this.status === 'limited' && !this.anyLost()) this.setStatus('connected');
    });
    subscription.on('unsubscribed', (ctx) => {
      // Code 1 = unauthorized: the API refused the token (permission removed, or its access
      // cache not yet refreshed after a change). Other codes: the server ended it. While a screen
      // still follows the channel it is never left silently dead (QA BUG-02): the connection
      // reports "limited" (a banner shows it) and retries with backoff. A screen that really
      // lost access shows "not found" and leaves the channel, which stops the retries.
      entry.denied = ctx.code === 1;
      entry.members.clear();
      this.notifyPresence(entry);
      if (this.channels.get(channel) === entry) this.scheduleRetry(entry);
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
    this.stopRetry(entry);
    if (this.status === 'limited' && !this.anyLost()) this.setStatus('connected');
    entry.subscription.unsubscribe();
    this.client.removeSubscription(entry.subscription);
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    const delay = RETRY_DELAYS_MS[Math.min(this.reconnects, RETRY_DELAYS_MS.length - 1)] ?? 30_000;
    this.reconnects += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.started) this.client.connect();
    }, delay);
  }

  private anyLost(): boolean {
    return [...this.channels.values()].some((entry) => entry.lost);
  }

  private scheduleRetry(entry: ChannelEntry): void {
    entry.lost = true;
    if (this.status === 'connected') this.setStatus('limited');
    if (entry.retryTimer !== null) return;
    const delay = RETRY_DELAYS_MS[Math.min(entry.retries, RETRY_DELAYS_MS.length - 1)] ?? 30_000;
    entry.retries += 1;
    entry.retryTimer = setTimeout(() => {
      entry.retryTimer = null;
      if (this.channels.get(entry.subscription.channel) === entry) entry.subscription.subscribe();
    }, delay);
  }

  private stopRetry(entry: ChannelEntry): void {
    if (entry.retryTimer !== null) clearTimeout(entry.retryTimer);
    entry.retryTimer = null;
    entry.lost = false;
    entry.retries = 0;
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
    // Visible to tests and to anyone diagnosing a proxy: which state, over which transport.
    document.documentElement.dataset.realtimeStatus = status;
    document.documentElement.dataset.realtimeTransport = this.transport ?? '';
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
