import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { PartsBase } from './incidentParts';
import { queryKeys } from './keys';
import type { components } from './schema';

// Your personal timers (WP-046a S3, REQ-INC-069): only ever yours, kept on the server, live on
// your personal channel (`work_items.my_timers_changed`). Stopping gives the times to prefill a
// worklog with; nothing is logged until you save it.

export type RecordTimer = components['schemas']['WorkItemTimerOut'];
export type StoppedTimer = components['schemas']['WorkItemTimerStoppedOut'];
export type MyTimer = components['schemas']['MyTimerOut'];

/** The same engine route under another type's prefix (as the other record parts). */
function at<P extends string>(base: PartsBase, path: P): P {
  return path.replace('/api/v1/incidents/', `/api/v1/${base}/`) as P;
}

export const timerKeys = {
  all: ['timers'] as const,
  record: (base: PartsBase, id: string) => ['timers', base, id] as const,
  mine: ['timers', 'mine'] as const,
};

/** Your running timer on a record, or null. */
export function useRecordTimer(id: string, base: PartsBase = 'incidents', enabled = true) {
  return useQuery({
    queryKey: timerKeys.record(base, id),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/{record_id}/timer'), {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}

/** Your running timers on every record you may still see. */
export function useMyTimers(enabled = true) {
  return useQuery({
    queryKey: timerKeys.mine,
    queryFn: () => call(api.GET('/api/v1/my-timers')),
    enabled,
  });
}

export type TimerChange =
  { kind: 'start'; comment?: string } | { kind: 'stop' } | { kind: 'discard' };

/** Start, stop (returns the worklog's prefill) or discard your timer on a record. */
export function useTimerChange(id: string, base: PartsBase = 'incidents') {
  const queryClient = useQueryClient();
  const path = { params: { path: { record_id: id } } };
  return useMutation({
    mutationFn: async (change: TimerChange): Promise<StoppedTimer | null> => {
      if (change.kind === 'start') {
        await call(
          api.POST(at(base, '/api/v1/incidents/{record_id}/timer'), {
            ...path,
            body: { comment: change.comment ?? null },
          }),
        );
        return null;
      }
      if (change.kind === 'stop') {
        return call(api.POST(at(base, '/api/v1/incidents/{record_id}/timer/stop'), path));
      }
      await call(api.DELETE(at(base, '/api/v1/incidents/{record_id}/timer'), path));
      return null;
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: timerKeys.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.worklogs(id) });
    },
  });
}

/** On opening a record: the type's auto-start, if it is on (the server decides; once ever). */
export function useAutoStartTimer(id: string, base: PartsBase = 'incidents') {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true }, // a convenience: a refusal says nothing
    mutationFn: () =>
      call(
        api.POST(at(base, '/api/v1/incidents/{record_id}/timer/auto'), {
          params: { path: { record_id: id } },
        }),
      ),
    onSuccess: (started) => {
      if (started !== null) void queryClient.invalidateQueries({ queryKey: timerKeys.all });
    },
  });
}
