import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, type ReactNode } from 'react';

import { queryKeys } from '@supportx/api-client';

import {
  ACCESS_CHANGED,
  ACCESS_REFETCH_SPREAD_MS,
  RealtimeConnection,
  type ClientFactory,
} from './connection';
import { RealtimeContext, type RealtimeContextValue } from './context';
import { REALTIME_KEY } from './keys';
import type { RealtimeMessage } from './types';

export interface RealtimeProviderProps {
  /** The session's tenant and user; without them there is no connection (signed out). */
  tenantId?: string;
  userId?: string;
  children: ReactNode;
  /** Tests pass a fake Centrifugo client. */
  factory?: ClientFactory;
}

/**
 * One realtime connection per session (architecture.md §8). A new tenant or user (switch, sign
 * out) closes the old connection and opens a new one. The provider itself follows the user's
 * own channel and the tenant-wide one: access and plan changes refresh the session, menus and
 * banners at once, and the server's "access changed" disconnect does the same on reconnect.
 */
export function RealtimeProvider({ tenantId, userId, children, factory }: RealtimeProviderProps) {
  const queryClient = useQueryClient();
  const value = useMemo<RealtimeContextValue | null>(
    () =>
      tenantId === undefined || userId === undefined
        ? null
        : { connection: new RealtimeConnection(factory), tenantId, userId },
    [tenantId, userId, factory],
  );

  useEffect(() => {
    if (value === null) return;
    const { connection } = value;
    const refreshAccess = () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.session });
      void queryClient.invalidateQueries({ queryKey: queryKeys.entitlements });
      void queryClient.invalidateQueries({ queryKey: queryKeys.access.all });
      void queryClient.invalidateQueries({ queryKey: REALTIME_KEY });
    };
    const own = (message: RealtimeMessage) => {
      if (message.type === 'access.changed' || message.type === 'refresh') refreshAccess();
      // What the person may see changed (a role, a group, a field rule, ADR-047): every screen
      // open now asks again, so a field just hidden reads "Not shown to you" with no refresh.
      // Rare, and only the active queries refetch, after a random 0-3 s: a rule reaches every
      // holder of a role at once, so their screens never ask the server all together (lane C).
      if (message.type === 'access.changed') {
        setTimeout(() => {
          void queryClient.invalidateQueries({ refetchType: 'active' });
        }, Math.random() * ACCESS_REFETCH_SPREAD_MS);
      }
      // The user's own record changed elsewhere (another device): name, preferences, layout.
      if (message.type === 'users.changed' && message.ids.includes(value.userId)) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session });
      }
    };
    const tenantWide = (message: RealtimeMessage) => {
      if (message.type === 'entitlements.changed' || message.type === 'refresh') refreshAccess();
    };
    const leaveOwn = connection.join(`t:${value.tenantId}:user:${value.userId}`, own);
    const leaveTenant = connection.join(`t:${value.tenantId}:broadcast`, tenantWide);
    const stopWatching = connection.onReconnect((code) => {
      if (code === ACCESS_CHANGED) refreshAccess();
    });
    // One connection per tab (QA BUG-02): acquire/release instead of connect/close, so React
    // StrictMode's unmount-and-remount in development keeps the same live connection.
    connection.acquire();
    // Leaving or reloading the page: say goodbye now, so others do not see this window as a
    // viewer until the server times it out (QA BUG-13, the "you, another window" ghost).
    const leave = () => {
      connection.close();
    };
    // A page only: React Native's global has no events (the app closes its connection itself).
    const page = typeof window.addEventListener === 'function' ? window : null;
    page?.addEventListener('pagehide', leave);
    return () => {
      page?.removeEventListener('pagehide', leave);
      leaveOwn();
      leaveTenant();
      stopWatching();
      connection.release();
    };
  }, [value, queryClient]);

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>;
}
