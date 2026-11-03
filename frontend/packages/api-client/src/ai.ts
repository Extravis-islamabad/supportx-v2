import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-037: the tenant's AI settings (Admin › AI). Every AI feature reads them to know whether it
// may show; a change reaches every screen live (`ai.settings_changed`).

export type AiSettings = components['schemas']['AiSettingsOut'];
export type AiSettingsInput = components['schemas']['AiSettingsPatch'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** A stale change: fetch the saved version, so the conflict dialog can compare. */
function onConflict(refresh: () => void) {
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) refresh();
  };
}

/** The AI switches, the features with their state, and the model. */
export function useAiSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.ai.settings,
    queryFn: () => call(api.GET('/api/v1/ai/settings')),
    enabled,
  });
}

/** Change the AI settings (If-Match); refusals come back by field. */
export function useSaveAiSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: AiSettingsInput; version: number }) =>
      call(api.PATCH('/api/v1/ai/settings', { params: { header: ifMatch(version) }, body })),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.ai.settings, saved);
    },
    onError: onConflict(
      () => void queryClient.invalidateQueries({ queryKey: queryKeys.ai.settings }),
    ),
  });
}
