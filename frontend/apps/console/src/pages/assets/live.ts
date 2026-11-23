import { useQueryClient } from '@tanstack/react-query';

import { ApiError, queryKeys, useUnits } from '@supportx/api-client';
import { usePersonalChannel, useTenantChannel } from '@supportx/realtime';
import { useLabel } from '@supportx/ui';

// Live refresh and lookups the stock and booking screens share (WP-049b s1; rule c).

export const CONSUMABLES_CHANGED = 'assets.consumables_changed';

/** Refetch every stock query when stock or a consumable changed (rule c; IDs only). */
export function useConsumablesLive() {
  const queryClient = useQueryClient();
  useTenantChannel((event) => {
    if (event.type !== CONSUMABLES_CHANGED) return;
    for (const part of ['consumables', 'consumable', 'ledger', 'request-allocations']) {
      void queryClient.invalidateQueries({ queryKey: ['assets', part] });
    }
  });
}

/** Site names by ID, for the stock rows ("No site" for central stock). */
export function useSiteNames(): (id: string | null | undefined) => string {
  const t = useLabel();
  const sites = useUnits('sites');
  const names = new Map((sites.data ?? []).map((s) => [s.id, s.name]));
  return (id) =>
    id == null ? t('assets.stock.no_site') : (names.get(id) ?? t('assets.stock.no_site'));
}

export const BOOKINGS_CHANGED = 'assets.bookings_changed';
/** Refetch bookings, availability and loans when a booking changed (rule c; IDs only). */
export function useBookingsLive() {
  const queryClient = useQueryClient();
  useTenantChannel((event) => {
    if (event.type !== BOOKINGS_CHANGED) return;
    for (const part of ['bookings', 'availability', 'loans', 'my-bookings', 'bookable']) {
      void queryClient.invalidateQueries({ queryKey: ['assets', part] });
    }
  });
}

/** The next free day the API suggests for a taken period, or null (REQ-AST-032 AC1). */
export function nextFree(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.code !== 'asset_booking_taken') return null;
  const value = error.params.next_free;
  return typeof value === 'string' && value !== '' ? value : null;
}

// WP-049b s3 (REQ-AST-039): the person's label jobs, on their own channel.
export const LABELS_CHANGED = 'assets.labels_changed';
/** Refetch label jobs and history when the person's jobs change (rule c; IDs only). */
export function useLabelsLive() {
  const queryClient = useQueryClient();
  usePersonalChannel((event) => {
    if (event.type !== LABELS_CHANGED) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.labelJobs });
    void queryClient.invalidateQueries({ queryKey: queryKeys.assets.labelPrintsAll });
  });
}
