import { useQuery } from '@tanstack/react-query';
import { Tag } from 'antd';

import { api, call, queryKeys } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/** How often the console re-checks the API while the page is open. */
export const API_STATUS_REFRESH_MS = 10_000;

async function fetchApiOnline(): Promise<boolean> {
  await call(api.GET('/api/v1/health'));
  return true;
}

/**
 * Live API status on the home page: polls GET /api/v1/health through the Vite dev proxy
 * and shows a green or red tag. All text comes from the labels package (CLAUDE.md rule d).
 */
export function ApiStatus() {
  const t = useLabel();
  const { isPending, isSuccess } = useQuery({
    queryKey: queryKeys.health,
    queryFn: fetchApiOnline,
    // The tag itself is the message: no toast for a failed health check.
    meta: { silent: true },
    refetchInterval: API_STATUS_REFRESH_MS,
    refetchIntervalInBackground: false,
    retry: false,
  });

  if (isPending) {
    return (
      <Tag role="status" color="default">
        {t('api_status.checking')}
      </Tag>
    );
  }
  return isSuccess ? (
    <Tag role="status" color="success">
      {t('api_status.online')}
    </Tag>
  ) : (
    <Tag role="status" color="error">
      {t('api_status.offline')}
    </Tag>
  );
}
