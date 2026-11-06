import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// The asset catalogue (WP-049a, D-141): product types in a tree, products, states, life cycles
// and the asset settings. Every query sits under `queryKeys.assets.all`, so the tenant event
// `assets.catalogue_changed` (no IDs in it, §5c) refetches them all at once. Writes send
// If-Match with the version the screen showed; a 409 refetches, never overwriting the other
// admin's change.

type S = components['schemas'];
export type AssetSettings = S['AssetSettingsOut'];
export type AssetSettingsInput = S['AssetSettingsIn'];
export type AssetState = S['AssetStateOut'];
export type AssetStateInput = S['AssetStateIn'];
export type AssetStatePatch = S['AssetStatePatch'];
export type AssetLifeCycle = S['AssetLifeCycleOut'];
export type AssetLifeCycleInput = S['AssetLifeCycleIn'];
export type AssetLifeCyclePatch = S['AssetLifeCyclePatch'];
export type AssetMove = S['AssetMoveIO'];
export type AssetMoveOption = S['AssetMoveOptionOut'];
export type AssetBulkMoveResult = S['AssetBulkMoveResult'];
export type AssetDisposal = S['AssetDisposalOut'];
export type AssetDisposalInput = S['AssetDisposalIn'];
export type AssetProductType = S['AssetProductTypeOut'];
export type AssetProductTypeInput = S['AssetProductTypeIn'];
export type AssetProductTypePatch = S['AssetProductTypePatch'];
export type AssetProduct = S['AssetProductOut'];
export type AssetProductInput = S['AssetProductIn'];
export type AssetProductPatch = S['AssetProductPatch'];
export type AssetTypeCategory = S['AssetTypeCategory'];
export type AssetTypeKind = S['AssetTypeKind'];
export type AssetStateCategory = S['AssetStateCategory'];
export type AssetAgeBasis = S['AssetAgeBasis'];
export type AssetDepreciationMethod = S['AssetDepreciationMethod'];

/** The products list: one product type's products (or all), newest change first. */
export interface AssetProductsQuery {
  productTypeId?: string;
}

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export function useAssetSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.settings,
    queryFn: () => call(api.GET('/api/v1/assets/settings')),
    enabled,
  });
}

export function useAssetStates(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.states,
    queryFn: () => call(api.GET('/api/v1/assets/states')),
    enabled,
  });
}

export function useAssetLifeCycles(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.lifeCycles,
    queryFn: () => call(api.GET('/api/v1/assets/life-cycles')),
    enabled,
  });
}

export function useAssetProductTypes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.productTypes,
    queryFn: () => call(api.GET('/api/v1/assets/product-types')),
    enabled,
  });
}

/** Products, cursor-paged: `fetchNextPage()` follows `next_cursor`. */
export function useAssetProducts(query: AssetProductsQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.assets.products(query),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/assets/products', {
          params: {
            query: {
              filter:
                query.productTypeId === undefined
                  ? undefined
                  : JSON.stringify({
                      field: 'product_type_id',
                      op: 'eq',
                      value: query.productTypeId,
                    }),
              sort: '-updated_at',
              limit: 50,
              cursor: pageParam ?? undefined,
              include_total: pageParam === null,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

/** One catalogue write. Creates carry the form's Idempotency-Key; the rest the version read. */
export type AssetCatalogueChange =
  | { kind: 'settings'; version: number; body: AssetSettingsInput }
  | { kind: 'create_state'; key: string; body: AssetStateInput }
  | { kind: 'state'; id: string; version: number; body: AssetStatePatch }
  | { kind: 'delete_state'; id: string; version: number }
  | { kind: 'create_life_cycle'; key: string; body: AssetLifeCycleInput }
  | { kind: 'life_cycle'; id: string; version: number; body: AssetLifeCyclePatch }
  | { kind: 'delete_life_cycle'; id: string; version: number }
  | { kind: 'create_product_type'; key: string; body: AssetProductTypeInput }
  | { kind: 'product_type'; id: string; version: number; body: AssetProductTypePatch }
  | { kind: 'delete_product_type'; id: string; version: number }
  | { kind: 'create_product'; key: string; body: AssetProductInput }
  | { kind: 'product'; id: string; version: number; body: AssetProductPatch }
  | { kind: 'delete_product'; id: string; version: number };

async function send(change: AssetCatalogueChange): Promise<unknown> {
  switch (change.kind) {
    case 'settings':
      return call(
        api.PATCH('/api/v1/assets/settings', {
          params: { header: ifMatch(change.version) },
          body: change.body,
        }),
      );
    case 'create_state':
      return call(
        api.POST('/api/v1/assets/states', {
          params: { header: { 'Idempotency-Key': change.key } },
          body: change.body,
        }),
      );
    case 'state':
      return call(
        api.PATCH('/api/v1/assets/states/{state_id}', {
          params: { header: ifMatch(change.version), path: { state_id: change.id } },
          body: change.body,
        }),
      );
    case 'delete_state':
      return call(
        api.DELETE('/api/v1/assets/states/{state_id}', {
          params: { header: ifMatch(change.version), path: { state_id: change.id } },
        }),
      );
    case 'create_life_cycle':
      return call(
        api.POST('/api/v1/assets/life-cycles', {
          params: { header: { 'Idempotency-Key': change.key } },
          body: change.body,
        }),
      );
    case 'life_cycle':
      return call(
        api.PATCH('/api/v1/assets/life-cycles/{life_cycle_id}', {
          params: { header: ifMatch(change.version), path: { life_cycle_id: change.id } },
          body: change.body,
        }),
      );
    case 'delete_life_cycle':
      return call(
        api.DELETE('/api/v1/assets/life-cycles/{life_cycle_id}', {
          params: { header: ifMatch(change.version), path: { life_cycle_id: change.id } },
        }),
      );
    case 'create_product_type':
      return call(
        api.POST('/api/v1/assets/product-types', {
          params: { header: { 'Idempotency-Key': change.key } },
          body: change.body,
        }),
      );
    case 'product_type':
      return call(
        api.PATCH('/api/v1/assets/product-types/{product_type_id}', {
          params: { header: ifMatch(change.version), path: { product_type_id: change.id } },
          body: change.body,
        }),
      );
    case 'delete_product_type':
      return call(
        api.DELETE('/api/v1/assets/product-types/{product_type_id}', {
          params: { header: ifMatch(change.version), path: { product_type_id: change.id } },
        }),
      );
    case 'create_product':
      return call(
        api.POST('/api/v1/assets/products', {
          params: { header: { 'Idempotency-Key': change.key } },
          body: change.body,
        }),
      );
    case 'product':
      return call(
        api.PATCH('/api/v1/assets/products/{product_id}', {
          params: { header: ifMatch(change.version), path: { product_id: change.id } },
          body: change.body,
        }),
      );
    case 'delete_product':
      return call(
        api.DELETE('/api/v1/assets/products/{product_id}', {
          params: { header: ifMatch(change.version), path: { product_id: change.id } },
        }),
      );
  }
}

/**
 * Change the catalogue (config.assets). Success or a conflict refetches the whole catalogue: a
 * type's move cascades its category to the descendants, so patching one row would be wrong.
 */
export function useAssetCatalogueChange() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  return useMutation({
    mutationFn: send,
    onSuccess: refresh,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
}

// --- the asset record (WP-049a s2) and vendors -------------------------------------------------

export type AssetRecord = S['AssetOut'];
export type AssetRecordInput = S['AssetIn'];
export type AssetRecordPatch = S['AssetPatch'];
export type AssetHistoryEntry = S['AssetHistoryEntryOut'];
export type Vendor = S['VendorOut'];
export type VendorInput = S['VendorIn'];
export type VendorPatch = S['VendorPatch'];

/** The asset list: free-text search, one product type, the trash. */
export interface AssetRecordsQuery {
  search?: string;
  productTypeId?: string;
  trash?: boolean;
}

/** Assets the person may see, cursor-paged, newest change first. */
export function useAssetRecords(query: AssetRecordsQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.assets.records(query),
    queryFn: ({ pageParam }) => {
      const params = {
        query: {
          search: query.search === undefined || query.search === '' ? undefined : query.search,
          filter:
            query.productTypeId === undefined
              ? undefined
              : JSON.stringify({ field: 'product_type_id', op: 'eq', value: query.productTypeId }),
          limit: 50,
          cursor: pageParam ?? undefined,
          include_total: pageParam === null,
        },
      };
      return call(
        query.trash === true
          ? api.GET('/api/v1/assets/trash', { params })
          : api.GET('/api/v1/assets', { params }),
      );
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

/** One asset; a 404 is an answer (deleted, or not for this person), not a reason to retry. */
export function useAssetRecord(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.record(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/assets/{asset_id}', { params: { path: { asset_id: id ?? '' } } })),
    enabled: id !== undefined,
    retry: false,
  });
}

/** An asset's history, newest first. */
export function useAssetHistory(id: string | undefined) {
  return useInfiniteQuery({
    queryKey: queryKeys.assets.history(id ?? ''),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/assets/{asset_id}/history', {
          params: {
            path: { asset_id: id ?? '' },
            query: { cursor: pageParam === null ? undefined : Number(pageParam), limit: 25 },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: id !== undefined,
  });
}

export type AssetRecordChange =
  | { kind: 'create'; key: string; body: AssetRecordInput }
  | { kind: 'update'; id: string; version: number; body: AssetRecordPatch }
  | { kind: 'delete'; id: string; version: number }
  | { kind: 'restore'; id: string };

/** Add, change, trash or restore an asset; the asset queries refetch after (and on a 409). */
export function useAssetRecordChange() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  return useMutation({
    mutationFn: async (change: AssetRecordChange): Promise<AssetRecord | undefined> => {
      switch (change.kind) {
        case 'create':
          return call(
            api.POST('/api/v1/assets', {
              params: { header: { 'Idempotency-Key': change.key } },
              body: change.body,
            }),
          );
        case 'update':
          return call(
            api.PATCH('/api/v1/assets/{asset_id}', {
              params: { header: ifMatch(change.version), path: { asset_id: change.id } },
              body: change.body,
            }),
          );
        case 'delete':
          await call(
            api.DELETE('/api/v1/assets/{asset_id}', {
              params: { header: ifMatch(change.version), path: { asset_id: change.id } },
            }),
          );
          return undefined;
        case 'restore':
          return call(
            api.POST('/api/v1/assets/{asset_id}/restore', {
              params: { path: { asset_id: change.id } },
            }),
          );
      }
    },
    onSuccess: refresh,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
}

/** Where an asset may move from its state now; moves you may not make come `allowed: false`. */
export function useAssetMoves(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.moves(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/moves', { params: { path: { asset_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** An asset's disposal record (REQ-AST-017); a 404 means it has none. */
export function useAssetDisposal(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.disposal(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/disposal', { params: { path: { asset_id: id ?? '' } } }),
      ),
    enabled: enabled && id !== undefined,
    retry: false,
    meta: { silent: true },
  });
}

/** Move, copy or bulk-move assets (WP-049a s3); every asset query refetches after. */
export function useAssetActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  const onError = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) refresh();
  };
  const move = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; toStateId: string; reason?: string }) =>
      call(
        api.POST('/api/v1/assets/{asset_id}/move', {
          params: { header: ifMatch(input.version), path: { asset_id: input.id } },
          body: { to_state_id: input.toStateId, reason: input.reason ?? null },
        }),
      ),
    onSuccess: refresh,
    onError,
  });
  const copy = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; count: number; key: string }) =>
      call(
        api.POST('/api/v1/assets/{asset_id}/copy', {
          params: { header: { 'Idempotency-Key': input.key }, path: { asset_id: input.id } },
          body: { count: input.count },
        }),
      ),
    onSuccess: refresh,
  });
  const bulkMove = useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      items: { asset_id: string; version: number }[];
      toStateId: string;
      reason?: string;
    }) =>
      call(
        api.POST('/api/v1/assets/bulk-moves', {
          body: { items: input.items, to_state_id: input.toStateId, reason: input.reason ?? null },
        }),
      ),
    onSettled: refresh,
  });
  const dispose = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; version: number; body: AssetDisposalInput }) =>
      call(
        api.POST('/api/v1/assets/{asset_id}/dispose', {
          params: { header: ifMatch(input.version), path: { asset_id: input.id } },
          body: input.body,
        }),
      ),
    onSuccess: refresh,
    onError,
  });
  return { move, copy, bulkMove, dispose };
}

/** Vendors by name (`activeOnly`: what new records may pick, REQ-PUR-001 AC2). */
export function useVendors(activeOnly = false, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.vendors.list(activeOnly),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/procurement/vendors', {
          params: {
            query: {
              filter: activeOnly
                ? JSON.stringify({ field: 'is_active', op: 'eq', value: true })
                : undefined,
              sort: 'name',
              limit: 200,
              cursor: pageParam ?? undefined,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

export type VendorChange =
  | { kind: 'create'; key: string; body: VendorInput }
  | { kind: 'update'; id: string; version: number; body: VendorPatch }
  | { kind: 'delete'; id: string; version: number };

/** Add, change or delete a vendor; the vendor queries refetch after (and on a 409). */
export function useVendorChange() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.vendors.all });
  return useMutation({
    mutationFn: async (change: VendorChange): Promise<Vendor | undefined> => {
      switch (change.kind) {
        case 'create':
          return call(
            api.POST('/api/v1/procurement/vendors', {
              params: { header: { 'Idempotency-Key': change.key } },
              body: change.body,
            }),
          );
        case 'update':
          return call(
            api.PATCH('/api/v1/procurement/vendors/{vendor_id}', {
              params: { header: ifMatch(change.version), path: { vendor_id: change.id } },
              body: change.body,
            }),
          );
        case 'delete':
          await call(
            api.DELETE('/api/v1/procurement/vendors/{vendor_id}', {
              params: { header: ifMatch(change.version), path: { vendor_id: change.id } },
            }),
          );
          return undefined;
      }
    },
    onSuccess: refresh,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
}
