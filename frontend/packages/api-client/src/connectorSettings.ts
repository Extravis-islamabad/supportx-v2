import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-040 (D-041): a tenant's connector defaults (integrations.manage). The card follows
// `integrations.connector_settings_changed` on the tenant channel and refetches.

export type ConnectorSettings = components['schemas']['ConnectorSettingsOut'];
export type ConnectorSettingsInput = components['schemas']['ConnectorSettingsIn'];

/** When a connector counts as failing, how long errors are kept, how often new ones sync. */
export function useConnectorSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.connectors.settings,
    queryFn: () => call(api.GET('/api/v1/integrations/connector-settings')),
    enabled,
  });
}

/** Save the fields sent (If-Match: the version read, 0 before the first save). */
export function useSaveConnectorSettings() {
  const queryClient = useQueryClient();
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: queryKeys.connectors.settings });
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: ConnectorSettingsInput; version: number }) =>
      call(
        api.PUT('/api/v1/integrations/connector-settings', {
          params: { header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: refresh,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
}
