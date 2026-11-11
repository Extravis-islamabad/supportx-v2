import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Consumable stock, minimum stock and bookings ahead (WP-049b s1; REQ-AST-032..035). Every query
// sits under `queryKeys.assets.all`, so set-up changes (`assets.catalogue_changed`) refetch them;
// the stock screens also follow `assets.consumables_changed` and the booking screens
// `assets.bookings_changed`. Quantities are exact decimals: strings from the API, never floats.

type S = components['schemas'];
export type AssetConsumable = S['AssetConsumableOut'];
export type AssetConsumableDetail = S['AssetConsumableDetailOut'];
export type AssetConsumableInput = S['AssetConsumableIn'];
export type AssetConsumablePatch = S['AssetConsumablePatch'];
export type AssetStock = S['AssetStockOut'];
export type AssetBatch = S['AssetBatchOut'];
export type AssetMovement = S['AssetMovementOut'];
export type AssetMovementKind = AssetMovement['kind'];
export type AssetRecipientKind = S['AssetAllocationIn']['recipient_kind'];
export type AssetReceiptInput = S['AssetReceiptIn'];
export type AssetAllocationInput = S['AssetAllocationIn'];
export type AssetAdjustmentInput = S['AssetAdjustmentIn'];
export type AssetStockReturnInput = S['AssetStockReturnIn'];
export type AssetStockRule = S['AssetStockRuleOut'];
export type AssetStockRuleInput = S['AssetStockRuleIn'];
export type AssetStockRulePatch = S['AssetStockRulePatch'];
export type AssetBooking = S['AssetBookingOut'];
export type AssetBookingInput = S['AssetBookingIn'];
export type AssetAvailability = S['AssetAvailabilityOut'];
export type MyAssetBookings = S['MyAssetBookingsOut'];
export type MyAssetBookingInput = S['MyAssetBookingIn'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });
const idempotent = (key: string) => ({ 'Idempotency-Key': key });

/** The consumables list's filters. */
export interface ConsumablesQuery {
  search?: string;
  siteId?: string;
}

/** Consumables kept in stock, with each site's stock and minimum (REQ-AST-033). */
export function useConsumables(query: ConsumablesQuery, enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.consumables(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/consumables', {
          params: {
            query: {
              search: query.search === '' ? undefined : query.search,
              site_id: query.siteId,
            },
          },
        }),
      ),
    enabled,
  });
}

/** One consumable with its stock and lots. */
export function useConsumable(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.consumable(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/consumables/{consumable_id}', {
          params: { path: { consumable_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** A consumable's ledger, newest first. */
export function useConsumableLedger(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.ledger(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/consumables/{consumable_id}/ledger', {
          params: { path: { consumable_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** What was allocated from a request (REQ-AST-034 AC2, the request's side). */
export function useRequestAllocations(workItemId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.requestAllocations(workItemId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/consumable-allocations', {
          params: { query: { work_item_id: workItemId ?? '' } },
        }),
      ),
    enabled: workItemId !== undefined,
  });
}

/** Keep consumables and move their stock; every asset query refetches after. */
export function useConsumableActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetConsumableInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/consumables', {
          params: { header: idempotent(input.key) },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; body: AssetConsumablePatch }) =>
      call(
        api.PATCH('/api/v1/assets/consumables/{consumable_id}', {
          params: { header: ifMatch(input.version), path: { consumable_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: async (input: { id: string; version: number }) => {
      await call(
        api.DELETE('/api/v1/assets/consumables/{consumable_id}', {
          params: { header: ifMatch(input.version), path: { consumable_id: input.id } },
        }),
      );
    },
    onSettled: refresh,
  });
  const receive = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; body: AssetReceiptInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/consumables/{consumable_id}/receipts', {
          params: { header: idempotent(input.key), path: { consumable_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const allocate = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; body: AssetAllocationInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/consumables/{consumable_id}/allocations', {
          params: { header: idempotent(input.key), path: { consumable_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const adjust = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; body: AssetAdjustmentInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/consumables/{consumable_id}/adjustments', {
          params: { header: idempotent(input.key), path: { consumable_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const returnStock = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; body: AssetStockReturnInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/consumables/{consumable_id}/returns', {
          params: { header: idempotent(input.key), path: { consumable_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  return { create, update, remove, receive, allocate, adjust, returnStock };
}

/** Minimum-stock rules (REQ-AST-035). */
export function useStockRules(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.stockRules,
    queryFn: () => call(api.GET('/api/v1/assets/stock-rules')),
    enabled,
  });
}

/** Add, change and remove minimum-stock rules (set-up: config.assets). */
export function useStockRuleActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetStockRuleInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/stock-rules', {
          params: { header: idempotent(input.key) },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; body: AssetStockRulePatch }) =>
      call(
        api.PATCH('/api/v1/assets/stock-rules/{rule_id}', {
          params: { header: ifMatch(input.version), path: { rule_id: input.id } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: async (input: { id: string; version: number }) => {
      await call(
        api.DELETE('/api/v1/assets/stock-rules/{rule_id}', {
          params: { header: ifMatch(input.version), path: { rule_id: input.id } },
        }),
      );
    },
    onSettled: refresh,
  });
  return { create, update, remove };
}

/** The bookings filters: one asset, or a product and site. */
export interface BookingsQuery {
  assetId?: string;
  productId?: string;
  siteId?: string;
}

/** Live bookings ahead, earliest first (REQ-AST-032). */
export function useAssetBookings(query: BookingsQuery, enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.bookings(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/bookings', {
          params: {
            query: {
              asset_id: query.assetId,
              product_id: query.productId,
              site_id: query.siteId,
            },
          },
        }),
      ),
    enabled,
  });
}

/** Bookable assets and when they are held: the booking calendar. */
export function useAssetAvailability(
  query: { productId?: string; siteId?: string; q?: string },
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.assets.availability(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/availability', {
          params: {
            query: {
              product_id: query.productId,
              site_id: query.siteId,
              q: query.q === '' ? undefined : query.q,
            },
          },
        }),
      ),
    enabled,
  });
}

/** Book, cancel, hand over (staff). */
export function useBookingActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  const book = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetBookingInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/bookings', {
          params: { header: idempotent(input.key) },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const cancel = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/assets/bookings/{booking_id}/cancel', {
          params: { header: ifMatch(input.version), path: { booking_id: input.id } },
        }),
      ),
    onSettled: refresh,
  });
  const handOver = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/assets/bookings/{booking_id}/handover', {
          params: { header: ifMatch(input.version), path: { booking_id: input.id } },
        }),
      ),
    onSettled: refresh,
  });
  return { book, cancel, handOver };
}

/** My bookings in the portal, and whether booking there is on. */
export function useMyBookings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.myBookings,
    queryFn: () => call(api.GET('/api/v1/assets/my-bookings')),
    enabled,
  });
}

/** What I may book from the portal, searched by `q`. */
export function useBookableAssets(q: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.bookable(q),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/bookable', { params: { query: { q: q === '' ? undefined : q } } }),
      ),
    enabled,
  });
}

/** Book for myself, cancel my own (the portal). */
export function useMyBookingActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  const book = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: MyAssetBookingInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/my-bookings', {
          params: { header: idempotent(input.key) },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const cancel = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/assets/my-bookings/{booking_id}/cancel', {
          params: { header: ifMatch(input.version), path: { booking_id: input.id } },
        }),
      ),
    onSettled: refresh,
  });
  return { book, cancel };
}
