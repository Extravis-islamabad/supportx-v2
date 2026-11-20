import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

// WP-057 S5a (REQ-AUD-011): where audit and sign-in entries stream. A webhook's signing secret is
// in a mutation's answer once (gcTime 0); the screen resets the mutation when its dialog closes.

export type SiemDestination = components['schemas']['SiemDestinationOut'];
export type SiemDestinationMade = components['schemas']['SiemDestinationMadeOut'];
export type SiemDestinationInput = components['schemas']['SiemDestinationIn'];
export type SiemTest = components['schemas']['SiemTestOut'];

export const siemKeys = {
  all: ['siem'] as const,
  list: ['siem', 'destinations'] as const,
};

/** The tenant's destinations, each with its health (audit.manage). */
export function useSiemDestinations(enabled = true) {
  return useQuery({
    queryKey: siemKeys.list,
    queryFn: () => call(api.GET('/api/v1/audit/siem/destinations')),
    enabled,
    refetchInterval: 30_000, // health moves with every delivery tick
  });
}

/** Add one (Idempotency-Key); a webhook's secret is in this answer only. */
export function useAddSiemDestination() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    gcTime: 0,
    mutationFn: ({ body, key }: { body: SiemDestinationInput; key: string }) =>
      call(
        api.POST('/api/v1/audit/siem/destinations', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: siemKeys.all }),
  });
}

/** Change one (If-Match); its cursors stay where they are. */
export function useChangeSiemDestination() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: SiemDestinationInput;
    }) =>
      call(
        api.PATCH('/api/v1/audit/siem/destinations/{destination_id}', {
          params: {
            path: { destination_id: id },
            header: { 'If-Match': `"${String(version)}"` },
          },
          body,
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: siemKeys.all }),
  });
}

/** Start a secret's rotation (a new one, shown once) or finish it. */
export function useRotateSiemSecret() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    gcTime: 0,
    mutationFn: ({ id, finish }: { id: string; finish: boolean }) =>
      call(
        api.POST('/api/v1/audit/siem/destinations/{destination_id}/rotate-secret', {
          params: { path: { destination_id: id } },
          body: { finish },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: siemKeys.all }),
  });
}

/** Send one test entry now; the answer says whether it arrived (an error is a code). */
export function useTestSiemDestination() {
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id }: { id: string }) =>
      call(
        api.POST('/api/v1/audit/siem/destinations/{destination_id}/test', {
          params: { path: { destination_id: id } },
        }),
      ),
  });
}

/** Stop streaming to one (soft). */
export function useRemoveSiemDestination() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id }: { id: string }) =>
      call(
        api.DELETE('/api/v1/audit/siem/destinations/{destination_id}', {
          params: { path: { destination_id: id } },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: siemKeys.all }),
  });
}
