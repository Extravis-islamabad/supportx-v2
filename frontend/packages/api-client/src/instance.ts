import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-042 (REQ-ADM-049, 050, 052): the tenant's instance settings. Everyone signed in reads them
// (defaults, languages offered); the organisation's configure right changes them.

export type TenantSettings = components['schemas']['TenantSettingsOut'];
export type TenantSettingsInput = components['schemas']['TenantSettingsPatch'];

export function useTenantSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.instance.settings,
    queryFn: () => call(api.GET('/api/v1/organization/settings')),
    enabled,
  });
}

/** Save with If-Match; a stale save refetches so the conflict dialog can compare. */
export function useSaveTenantSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: TenantSettingsInput; version: number }) =>
      call(
        api.PATCH('/api/v1/organization/settings', {
          params: { header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.instance.settings, saved);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.instance.settings });
      }
    },
  });
}
