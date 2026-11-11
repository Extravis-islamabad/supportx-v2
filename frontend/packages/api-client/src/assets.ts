import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components, operations } from './schema';

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
export type AssetHolding = S['AssetHoldingOut'];
export type AssetLink = S['AssetLinkOut'];
export type AssetLinkKind = S['AssetLinkIn']['kind'];
export type AssetGroup = S['AssetGroupOut'];
export type AssetGroupInput = S['AssetGroupIn'];
export type MyAsset = S['MyAssetOut'];
export type AssetLoan = S['LoanOut'];
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
  /** Part of a name, manufacturer or part number (the searching product picker). */
  search?: string;
}

/** The shared filter DSL (§6.5) for a products query: one type, and/or a text search. */
function productsFilter(query: AssetProductsQuery): string | undefined {
  const parts: object[] = [];
  if (query.productTypeId !== undefined) {
    parts.push({ field: 'product_type_id', op: 'eq', value: query.productTypeId });
  }
  const text = query.search?.trim() ?? '';
  if (text !== '') {
    parts.push({
      or: ['name', 'manufacturer', 'part_number'].map((field) => ({
        field,
        op: 'contains',
        value: text,
      })),
    });
  }
  if (parts.length === 0) return undefined;
  return JSON.stringify(parts.length === 1 ? parts[0] : { and: parts });
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
              filter: productsFilter(query),
              sort: query.search === undefined ? '-updated_at' : 'name',
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

/** One product (the picker's current choice when it is not on the loaded page). */
export function useAssetProduct(id: string | undefined) {
  return useQuery({
    queryKey: [...queryKeys.assets.all, 'product', id ?? ''],
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/products/{product_id}', {
          params: { path: { product_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined && id !== '',
    retry: false,
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

type HistoryQuery = NonNullable<
  operations['asset_history_api_v1_assets__asset_id__history_get']['parameters']['query']
>;
/** Where a change came from (UI, API, rule, import ...), as the history filter takes it. */
export type AssetHistorySource = NonNullable<HistoryQuery['source']>[number];

/** REQ-AST-049: the history's filters (all optional; days are UTC days, inclusive). */
export interface AssetHistoryFilters {
  view?: 'all' | 'state' | 'assignment';
  field?: string;
  source?: AssetHistorySource;
  actorId?: string;
  since?: string;
  until?: string;
}

/** An asset's history, newest first, narrowed by `filters`. */
export function useAssetHistory(id: string | undefined, filters: AssetHistoryFilters = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.assets.historyFiltered(id ?? '', filters),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/assets/{asset_id}/history', {
          params: {
            path: { asset_id: id ?? '' },
            query: {
              cursor: pageParam === null ? undefined : Number(pageParam),
              limit: 25,
              view: filters.view,
              field: filters.field === undefined ? undefined : [filters.field],
              source: filters.source === undefined ? undefined : [filters.source],
              actor_id: filters.actorId,
              since: filters.since,
              until: filters.until,
            },
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

/** Who held an asset, newest first (REQ-AST-019). */
export function useAssetHoldings(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.holdings(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/holdings', { params: { path: { asset_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** An asset's links from both ends (REQ-AST-027). */
export function useAssetLinks(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.links(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/{asset_id}/links', { params: { path: { asset_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** The assets fitted to this one (its components, REQ-AST-026). */
export function useAssetComponents(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.components(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets', {
          params: {
            query: {
              filter: JSON.stringify({ field: 'parent_asset_id', op: 'eq', value: id }),
              limit: 100,
            },
          },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** What I hold, with each acknowledgement (REQ-AST-024); for requesters too. */
export function useMyAssets(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.mine,
    queryFn: () => call(api.GET('/api/v1/assets/mine')),
    enabled,
  });
}

/** Accept or dispute an asset given to me (REQ-AST-023). */
export function useAnswerAcknowledgement() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      id: string;
      accept: boolean;
      comment?: string;
      channel?: 'portal' | 'console';
    }) =>
      call(
        api.POST('/api/v1/assets/acknowledgements/{acknowledgement_id}/answer', {
          params: { path: { acknowledgement_id: input.id } },
          body: {
            accept: input.accept,
            comment: input.comment ?? null,
            channel: input.channel ?? 'portal',
          },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.mine }),
  });
}

/** Asset groups with their counts (REQ-AST-028). */
export function useAssetGroups(enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.groups,
    queryFn: () => call(api.GET('/api/v1/assets/groups')),
    enabled,
  });
}

/** A group's assets (the ones I may see). */
export function useAssetGroupAssets(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.assets.groupAssets(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/groups/{group_id}/assets', {
          params: { path: { group_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** The loan register's filters (REQ-AST-030): one status, one site. */
export interface AssetLoansQuery {
  status?: AssetLoan['status'];
  siteId?: string;
}

/** The loan register: loans still out, earliest due first, or one status and site. */
export function useAssetLoans(query: AssetLoansQuery = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.loanList(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/loans', {
          params: { query: { status: query.status, site_id: query.siteId } },
        }),
      ),
    enabled,
  });
}

/** What can go on a new loan now (loanable, in stock, not out), searched by `q`. */
export function useLoanableAssets(q: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.assets.loanable(q),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/loanable', { params: { query: { q: q === '' ? undefined : q } } }),
      ),
    enabled,
  });
}

/** Make loans, take assets back, mark assets loanable; every asset query refetches after. */
export function useLoanActions() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  const createLoan = useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      borrowerId: string;
      assetIds: string[];
      dueAt: string;
      comment?: string;
      departmentId?: string | null;
      siteId?: string | null;
      key: string;
    }) =>
      call(
        api.POST('/api/v1/assets/loans', {
          params: { header: { 'Idempotency-Key': input.key } },
          body: {
            borrower_id: input.borrowerId,
            asset_ids: input.assetIds,
            due_at: input.dueAt,
            comment: input.comment ?? null,
            department_id: input.departmentId ?? null,
            site_id: input.siteId ?? null,
          },
        }),
      ),
    onSettled: refresh,
  });
  const returnItems = useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      loanId: string;
      assetIds: string[];
      outcome: 'in_stock' | 'in_repair';
      comment?: string;
    }) =>
      call(
        api.POST('/api/v1/assets/loans/{loan_id}/returns', {
          params: { path: { loan_id: input.loanId } },
          body: {
            asset_ids: input.assetIds,
            outcome: input.outcome,
            comment: input.comment ?? null,
          },
        }),
      ),
    onSettled: refresh,
  });
  const setLoanable = useMutation({
    meta: { silent: true },
    mutationFn: (input: { assetIds: string[]; loanable: boolean }) =>
      call(
        api.POST('/api/v1/assets/loanable', {
          body: { asset_ids: input.assetIds, loanable: input.loanable },
        }),
      ),
    onSettled: refresh,
  });
  return { createLoan, returnItems, setLoanable };
}

/** Holders, links and groups: every asset query refetches after. */
export function useAssetRelations() {
  const queryClient = useQueryClient();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
  const setHolder = useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      id: string;
      version: number;
      holder: { kind: 'user' | 'department' | 'asset'; id: string } | null;
    }) =>
      input.holder === null
        ? call(
            api.DELETE('/api/v1/assets/{asset_id}/holder', {
              params: { header: ifMatch(input.version), path: { asset_id: input.id } },
            }),
          )
        : call(
            api.PUT('/api/v1/assets/{asset_id}/holder', {
              params: { header: ifMatch(input.version), path: { asset_id: input.id } },
              body: input.holder,
            }),
          ),
    onSettled: refresh,
  });
  const addLink = useMutation({
    meta: { silent: true },
    mutationFn: (input: { id: string; to: string; kind: AssetLinkKind; key: string }) =>
      call(
        api.POST('/api/v1/assets/{asset_id}/links', {
          params: { header: { 'Idempotency-Key': input.key }, path: { asset_id: input.id } },
          body: { to_asset_id: input.to, kind: input.kind },
        }),
      ),
    onSettled: refresh,
  });
  const removeLink = useMutation({
    meta: { silent: true },
    mutationFn: async (input: { id: string; linkId: string }) => {
      await call(
        api.DELETE('/api/v1/assets/{asset_id}/links/{link_id}', {
          params: { path: { asset_id: input.id, link_id: input.linkId } },
        }),
      );
    },
    onSettled: refresh,
  });
  const createGroup = useMutation({
    meta: { silent: true },
    mutationFn: (input: { body: AssetGroupInput; key: string }) =>
      call(
        api.POST('/api/v1/assets/groups', {
          params: { header: { 'Idempotency-Key': input.key } },
          body: input.body,
        }),
      ),
    onSettled: refresh,
  });
  const addMembers = useMutation({
    meta: { silent: true },
    mutationFn: (input: { groupId: string; assetIds: string[] }) =>
      call(
        api.POST('/api/v1/assets/groups/{group_id}/members', {
          params: { path: { group_id: input.groupId } },
          body: { asset_ids: input.assetIds },
        }),
      ),
    onSettled: refresh,
  });
  return { setHolder, addLink, removeLink, createGroup, addMembers };
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
