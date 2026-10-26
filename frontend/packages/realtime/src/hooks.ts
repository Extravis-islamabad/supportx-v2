import { useQuery, type QueryClient, type QueryKey } from '@tanstack/react-query';
import {
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';

import { fetchListChannels } from '@supportx/api-client';

import { listChannelsKey } from './keys';
import { RealtimeContext } from './context';
import type { ConnectionStatus, PresenceMember, RealtimeMessage } from './types';

type Listener = (message: RealtimeMessage) => void;

/** The latest `listener` without re-subscribing when it changes identity. */
function useLatest(listener: Listener): { current: Listener } {
  const ref = useRef(listener);
  useLayoutEffect(() => {
    ref.current = listener;
  });
  return ref;
}

const noStatus = () => () => undefined;

/** Live, reconnecting, polling… (`offline` outside a session). */
export function useRealtimeStatus(): ConnectionStatus {
  const context = useContext(RealtimeContext);
  return useSyncExternalStore(
    context === null ? noStatus : (notify) => context.connection.onStatus(notify),
    () => (context === null ? 'offline' : context.connection.currentStatus),
  );
}

/** Follow one channel (null: none). Messages carry IDs and field names, never data. */
export function useChannel(channel: string | null, onMessage: Listener): void {
  const context = useContext(RealtimeContext);
  const latest = useLatest(onMessage);
  useEffect(() => {
    if (context === null || channel === null) return;
    return context.connection.join(channel, (message) => {
      latest.current(message);
    });
  }, [context, channel, latest]);
}

/**
 * Follow the tenant-wide channel: signals for everyone in the tenant ("announcements changed",
 * "plan changed"). They never carry IDs: the listener refetches and the API filters.
 */
export function useTenantChannel(onMessage: Listener): void {
  const context = useContext(RealtimeContext);
  useChannel(context === null ? null : `t:${context.tenantId}:broadcast`, onMessage);
}

/**
 * Follow the signed-in user's own channel (`t:{tenant}:user:{id}`): what concerns only them, such
 * as the scan state of the images they just pasted into an editor (WP-022).
 */
export function usePersonalChannel(onMessage: Listener): void {
  const context = useContext(RealtimeContext);
  useChannel(context === null ? null : `t:${context.tenantId}:user:${context.userId}`, onMessage);
}

/**
 * Follow a list (`users`, `roles`…): the API says which channels this user may join (one per
 * audience: everyone, their sites, their groups, their own records), then all are followed.
 */
export function useListChannel(list: string | null, onMessage: Listener): void {
  const context = useContext(RealtimeContext);
  const latest = useLatest(onMessage);
  const channels = useQuery({
    queryKey: listChannelsKey(context?.tenantId ?? '', list ?? ''),
    queryFn: () => fetchListChannels(list ?? ''),
    enabled: context !== null && list !== null,
    staleTime: Infinity,
    // Not being able to follow a list live is not an error to show: the list itself still
    // loads (and reports its own errors); it just does not update by itself.
    meta: { silent: true },
  });
  const names = (channels.data ?? []).join('|');
  useEffect(() => {
    if (context === null || names === '') return;
    const leave = names.split('|').map((channel) =>
      context.connection.join(channel, (message) => {
        latest.current(message);
      }),
    );
    return () => {
      for (const off of leave) off();
    };
  }, [context, names, latest]);
}

/**
 * Follow one record (`kind` = channel kind, e.g. `users`; `wi` for work items) and see who else
 * has it open. Returns the other viewers (other connections; may include the same person on
 * another device).
 */
export function useRecordChannel(
  kind: string,
  id: string | undefined,
  onMessage: Listener,
): PresenceMember[] {
  const context = useContext(RealtimeContext);
  const channel =
    context === null || id === undefined ? null : `t:${context.tenantId}:${kind}:${id}`;
  const latest = useLatest(onMessage);
  const [viewers, setViewers] = useState<PresenceMember[]>([]);
  useEffect(() => {
    if (context === null || channel === null) return;
    const leave = context.connection.join(
      channel,
      (message) => {
        latest.current(message);
      },
      true,
    );
    const unwatch = context.connection.watchPresence(channel, setViewers);
    return () => {
      unwatch();
      leave();
      setViewers([]);
    };
  }, [context, channel, latest]);
  return viewers;
}

/** The signed-in user's ID inside the realtime provider (to tell "you" from others). */
export function useRealtimeUser(): string | null {
  return useContext(RealtimeContext)?.userId ?? null;
}

/**
 * Cache helpers (architecture.md §8.3, "patch, then reconcile"): refetch only what a message
 * names, and only if the cached copy is older than the change.
 */
export function refreshList(queryClient: QueryClient, queryKey: QueryKey): void {
  void queryClient.invalidateQueries({ queryKey, refetchType: 'active' });
}

export function refreshRecord(
  queryClient: QueryClient,
  queryKey: QueryKey,
  message: RealtimeMessage,
): void {
  const cached = queryClient.getQueryData<{ version?: number }>(queryKey);
  if (
    message.version !== undefined &&
    cached?.version !== undefined &&
    cached.version >= message.version
  ) {
    return; // we already have this version (often: our own save)
  }
  void queryClient.invalidateQueries({ queryKey, refetchType: 'active' });
}
