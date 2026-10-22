import { useQuery } from '@tanstack/react-query';
import { Tag } from 'antd';

import { useLabel } from '@supportx/ui';

/** How often the console re-checks the API while the page is open. */
export const API_STATUS_REFRESH_MS = 10_000;
const HEALTH_URL = '/api/v1/health';

async function fetchApiOnline(): Promise<boolean> {
  // Only the HTTP outcome matters here, so no response body type is needed: API types come from
  // the generated api-client (WP-010), never hand-written copies.
  const response = await fetch(HEALTH_URL, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    throw new Error(`health check returned ${String(response.status)}`);
  }
  return true;
}

/**
 * Live API status for the console header: polls GET /api/v1/health through the Vite dev proxy
 * and shows a green or red tag. All text comes from the labels package (CLAUDE.md rule d).
 */
export function ApiStatus() {
  const t = useLabel();
  const { isPending, isSuccess } = useQuery({
    queryKey: ['system', 'health'],
    queryFn: fetchApiOnline,
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
