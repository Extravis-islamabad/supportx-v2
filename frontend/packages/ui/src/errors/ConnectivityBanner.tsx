import { Alert, Spin } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import {
  api,
  currentConnectivity,
  onConnectivity,
  reportConnectivity,
  type Connectivity,
} from '@supportx/api-client';

import { useRealtimeStatus } from '@supportx/realtime';

import { useLabel } from '../appearance';

export const RECONNECT_INTERVAL_MS = 3_000;
/** A realtime reconnect shorter than this is not worth a banner (it recovers what it missed). */
export const REALTIME_GRACE_MS = 2_000;

/** Realtime trouble worth telling the user about: a reconnect that lasts, or polling. */
function useRealtimeTrouble(): 'reconnecting' | 'polling' | null {
  const status = useRealtimeStatus();
  const [lasting, setLasting] = useState(false);
  const reconnecting = status === 'reconnecting';
  useEffect(() => {
    if (!reconnecting) return;
    const timer = setTimeout(() => {
      setLasting(true);
    }, REALTIME_GRACE_MS);
    return () => {
      clearTimeout(timer);
      setLasting(false);
    };
  }, [reconnecting]);
  if (status === 'polling') return 'polling';
  return reconnecting && lasting ? 'reconnecting' : null;
}

/**
 * "Reconnecting…" while the API is unreachable. Probes /health every few seconds and, once it
 * answers, clears itself and refetches what is on screen. Also shown while live updates are
 * reconnecting for more than a moment, and as "updating every few seconds" while the realtime
 * connection fell back to polling (WebSockets and streaming blocked, architecture.md §8.3).
 */
export function ConnectivityBanner() {
  const t = useLabel();
  const queryClient = useQueryClient();
  const [state, setState] = useState<Connectivity>(currentConnectivity);
  const realtime = useRealtimeTrouble();

  useEffect(() => onConnectivity(setState), []);

  useEffect(() => {
    if (state === 'online') return;
    const timer = setInterval(() => {
      api.GET('/api/v1/health').then(
        ({ response }) => {
          if (response.ok) {
            reportConnectivity('online');
            void queryClient.invalidateQueries();
          }
        },
        () => undefined, // still down; keep trying
      );
    }, RECONNECT_INTERVAL_MS);
    return () => {
      clearInterval(timer);
    };
  }, [state, queryClient]);

  if (state === 'online' && realtime === 'polling') {
    return (
      <Alert
        role="status"
        data-testid="realtime-polling-banner"
        type="info"
        banner
        showIcon
        message={t('connectivity.polling')}
      />
    );
  }
  if (state === 'online' && realtime === null) return null;
  return (
    <Alert
      role="status"
      data-testid="reconnecting-banner"
      type="warning"
      banner
      showIcon
      icon={<Spin size="small" />}
      message={t('connectivity.reconnecting')}
    />
  );
}
