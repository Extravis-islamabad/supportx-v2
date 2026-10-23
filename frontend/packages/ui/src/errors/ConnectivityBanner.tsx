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

import { useLabel } from '../appearance';

export const RECONNECT_INTERVAL_MS = 3_000;

/**
 * "Reconnecting…" while the API is unreachable. Probes /health every few seconds and, once it
 * answers, clears itself and refetches what is on screen.
 */
export function ConnectivityBanner() {
  const t = useLabel();
  const queryClient = useQueryClient();
  const [state, setState] = useState<Connectivity>(currentConnectivity);

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

  if (state === 'online') return null;
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
