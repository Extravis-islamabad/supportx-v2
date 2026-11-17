import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// A custom field's sensitive mark (WP-057 S3b-2b, REQ-SEC-040): sealed at rest when on. The
// stored values follow in a background job (`seal_state` sealing/opening, then sealed/plain);
// `metadata.custom_fields_changed` refetches everything under `customFields.all`, this too.

export type FieldSensitivity = components['schemas']['SensitivityOut'];
export type FieldSealState = components['schemas']['SealState'];

const sensitivityKey = (id: string) => [...queryKeys.customFields.all, 'sensitivity', id] as const;

/** GET /custom-fields/{id}/sensitivity: the mark, where values stand, records affected. */
export function useFieldSensitivity(id: string, enabled = true) {
  return useQuery({
    queryKey: sensitivityKey(id),
    enabled,
    queryFn: () =>
      call(
        api.GET('/api/v1/custom-fields/{field_id}/sensitivity', {
          params: { path: { field_id: id } },
        }),
      ),
  });
}

export interface SensitivityChange {
  id: string;
  version: number;
  sensitive: boolean;
  /** Required to turn it off (kept in the audit log). */
  reason?: string;
  /** The field's English name typed back (required to turn it off). */
  confirmName?: string;
}

/** Turn the mark on or off (a recent sign-in; the screen shows field errors itself). */
export function useSetFieldSensitivity() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (change: SensitivityChange) =>
      call(
        api.PUT('/api/v1/custom-fields/{field_id}/sensitivity', {
          params: {
            path: { field_id: change.id },
            header: { 'If-Match': `"${String(change.version)}"` },
          },
          body: {
            sensitive: change.sensitive,
            reason: change.reason ?? null,
            confirm_name: change.confirmName ?? null,
          },
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.customFields.all });
    },
  });
}
