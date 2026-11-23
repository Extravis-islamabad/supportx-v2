import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// A person's cost per hour (REQ-INC-068). Money: the screen asks only when the viewer holds
// `users.view_cost_rates`, and the server refuses otherwise. Amounts are exact decimals (strings
// from the API, never floats). The `user_cost_rates` list channel names the person whose rates
// changed; the card refetches them.

type S = components['schemas'];
export type CostRates = S['CostRatesOut'];
export type CostRate = S['CostRateOut'];
export type CostRateInput = S['CostRateIn'];
export type CostRatePatch = S['CostRatePatch'];
export type CostRateState = S['RateState'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** The person's rates, newest start first, and the one in force now. */
export function useCostRates(userId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.users.costRates(userId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/users/{user_id}/cost-rates', {
          params: { path: { user_id: userId ?? '' } },
        }),
      ),
    enabled: enabled && userId !== undefined,
  });
}

/** Set, change and remove a person's rates; the rates refetch after. */
export function useCostRateActions(userId: string) {
  const queryClient = useQueryClient();
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: queryKeys.users.costRates(userId) });
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: CostRateInput; key: string }) =>
      call(
        api.POST('/api/v1/users/{user_id}/cost-rates', {
          params: { header: { 'Idempotency-Key': input.key }, path: { user_id: userId } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; body: CostRatePatch }) =>
      call(
        api.PATCH('/api/v1/users/{user_id}/cost-rates/{rate_id}', {
          params: { header: ifMatch(input.version), path: { user_id: userId, rate_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: async (input: { id: string; version: number }) => {
      await call(
        api.DELETE('/api/v1/users/{user_id}/cost-rates/{rate_id}', {
          params: { header: ifMatch(input.version), path: { user_id: userId, rate_id: input.id } },
        }),
      );
    },
    onSettled: refresh,
  });
  return { create, update, remove };
}
