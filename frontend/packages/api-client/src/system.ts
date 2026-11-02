import { useQuery } from '@tanstack/react-query';

import { api } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Event delivery (must-fix before the pilot, 2026-10-28): whether the event workers deliver.
// /ready answers 503 when the API itself is not ready; its body says why either way, so this
// reads the body of both answers.
export type Readiness = components['schemas']['ReadinessResponse'];

export function useEventDelivery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.eventDelivery,
    queryFn: async (): Promise<Readiness> => {
      const { data, error } = await api.GET('/api/v1/ready');
      const body = data ?? (error as Readiness | undefined);
      if (body === undefined) throw new Error('readiness answered without a body');
      return body;
    },
    enabled,
    refetchInterval: 30_000,
    meta: { silent: true },
  });
}
