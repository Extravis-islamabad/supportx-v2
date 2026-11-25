import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// A CI's downtimes (WP-053 S5b, REQ-CMDB-020): from a change, a release or an incident (read-only
// here, changed at their record) or recorded on the CI by hand (`cmdb.record_downtime`). The
// list and its counts move live on the CI's channel (field `downtimes`).
export type CiDowntime = components['schemas']['CiDowntimeOut'];
export type CiDowntimes = components['schemas']['CiDowntimesOut'];
export type CiDowntimeInput = components['schemas']['CiDowntimeIn'];
export type CiDowntimePatch = components['schemas']['CiDowntimePatch'];
export type CiDowntimeState = components['schemas']['CiDowntimeState'];
export type CiDowntimeSource = components['schemas']['CiDowntimeSource'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** A CI's downtimes, newest start first, and how many in each state. */
export function useCiDowntimes(ciId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.cmdb.downtimes(ciId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/cis/{ci_id}/downtimes', {
          params: { path: { ci_id: ciId ?? '' } },
        }),
      ),
    enabled: ciId !== undefined,
  });
}

/** Record one by hand. `key` is the form's Idempotency-Key: a retried save makes no second one. */
export function useRecordCiDowntime(ciId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: CiDowntimeInput; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/cis/{ci_id}/downtimes', {
          params: { path: { ci_id: ciId }, header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.downtimes(ciId) });
    },
  });
}

/** Change a hand-recorded one (If-Match on its own version). */
export function useUpdateCiDowntime(ciId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, body }: { id: string; version: number; body: CiDowntimePatch }) =>
      call(
        api.PATCH('/api/v1/cmdb/cis/{ci_id}/downtimes/{downtime_id}', {
          params: { path: { ci_id: ciId, downtime_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.downtimes(ciId) });
    },
  });
}

/** Remove a hand-recorded one (If-Match on its own version). */
export function useRemoveCiDowntime(ciId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/cmdb/cis/{ci_id}/downtimes/{downtime_id}', {
          params: { path: { ci_id: ciId, downtime_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.downtimes(ciId) });
    },
  });
}
