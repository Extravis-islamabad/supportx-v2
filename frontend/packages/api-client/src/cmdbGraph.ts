import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// The CMDB's relationships, maps, business views and versions (WP-053 S2, REQ-CMDB-006..009,
// 024). Reads are the reader's own sight: a CI they may not open is a restricted placeholder
// with a per-answer key, never its ID (lane C's condition 2).
export type RelationshipType = components['schemas']['RelationshipTypeOut'];
export type RelationshipTypeInput = components['schemas']['RelationshipTypeIn'];
export type RelationshipTypePatch = components['schemas']['RelationshipTypePatch'];
export type RelationshipRule = components['schemas']['RelationshipRuleIn'];
export type RelationshipDirection = components['schemas']['RelationshipDirection'];
export type CiGraph = components['schemas']['CiGraphOut'];
export type CiMapNode = components['schemas']['CiNodeOut'];
export type CiMapEdge = components['schemas']['CiEdgeOut'];
export type CiVersionItem = components['schemas']['CiVersionItemOut'];
export type CiVersion = components['schemas']['CiVersionOut'];
export type CiVersionLink = components['schemas']['CiVersionLinkOut'];
export type CiComparison = components['schemas']['CiComparisonOut'];
export type CiAttributeChange = components['schemas']['CiAttributeChangeOut'];
export type BusinessViewLayout = components['schemas']['BusinessViewLayout'];
export type BusinessViewFilters = components['schemas']['BusinessViewFilters'];
export type BusinessViewListItem = components['schemas']['BusinessViewListItem'];
export type BusinessView = components['schemas']['BusinessViewOut'];
export type BusinessViewInput = components['schemas']['BusinessViewIn'];
export type BusinessViewPatch = components['schemas']['BusinessViewPatch'];

/** A map's filters, as the neighbours call takes them. */
export interface NeighboursQuery {
  depth: number;
  types: string[];
  ciTypes: string[];
  eol: boolean;
}

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Relationship types (with their rules); `forCiType`: only those a CI of that type may use. */
export function useRelationshipTypes(forCiType?: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.relationshipTypes(forCiType ?? null),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/relationship-types', {
          params: { query: { for_ci_type: forCiType } },
        }),
      ),
    enabled,
  });
}

/** One CI's map: nodes and edges to `depth`, at most `node_max` nodes (`truncated` past it). */
export function useNeighbours(ciId: string | undefined, query: NeighboursQuery, enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.neighbours(ciId ?? '', query),
    queryFn: () => neighbours(ciId ?? '', query),
    enabled: enabled && ciId !== undefined,
    retry: false,
    placeholderData: (previous) => previous,
  });
}

/** The neighbours call itself, for expanding a node (one call per expanded node). */
export function neighbours(ciId: string, query: NeighboursQuery): Promise<CiGraph> {
  return call(
    api.GET('/api/v1/cmdb/cis/{ci_id}/neighbours', {
      params: {
        path: { ci_id: ciId },
        query: {
          depth: query.depth,
          types: query.types.length === 0 ? undefined : query.types,
          ci_types: query.ciTypes.length === 0 ? undefined : query.ciTypes,
          eol: query.eol,
        },
      },
    }),
  );
}

/** A relationship changed: every open map, version list and the CIs' records refetch (§8.3). */
function useGraphChanged() {
  const queryClient = useQueryClient();
  return (ciIds: readonly string[]) => {
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.all, 'neighbours'] });
    for (const id of ciIds) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.detail(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.history(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.versions(id) });
    }
  };
}

/** Link a CI to up to 50 others, all or nothing; `key` is the dialog's Idempotency-Key. */
export function useAddRelationships(ciId: string) {
  const changed = useGraphChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      typeId,
      direction,
      targets,
      key,
    }: {
      typeId: string;
      direction: RelationshipDirection;
      targets: string[];
      key: string;
    }) =>
      call(
        api.POST('/api/v1/cmdb/cis/{ci_id}/relationships', {
          params: { path: { ci_id: ciId }, header: { 'Idempotency-Key': key } },
          body: { type_id: typeId, direction, targets },
        }),
      ),
    onSuccess: (_, { targets }) => {
      changed([ciId, ...targets]);
    },
  });
}

/** Unlink two CIs (If-Match: the relationship's version). */
export function useRemoveRelationship() {
  const changed = useGraphChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number; ciIds: string[] }) =>
      call(
        api.DELETE('/api/v1/cmdb/relationships/{relationship_id}', {
          params: { path: { relationship_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: (_, { ciIds }) => {
      changed(ciIds);
    },
  });
}

function useTypesSaved() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.all, 'relationship-types'] });
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.all, 'neighbours'] });
  };
}

export function useCreateRelationshipType() {
  const saved = useTypesSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: RelationshipTypeInput; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/relationship-types', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateRelationshipType() {
  const saved = useTypesSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      changes,
      version,
    }: {
      id: string;
      changes: RelationshipTypePatch;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/cmdb/relationship-types/{type_id}', {
          params: { path: { type_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

/** Remove a tenant's own type; 409 `cmdb_relationship_type_in_use` while links use it. */
export function useDeleteRelationshipType() {
  const saved = useTypesSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/cmdb/relationship-types/{type_id}', {
          params: { path: { type_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: saved,
  });
}

/** A CI's saved versions, newest first. */
export function useCiVersions(ciId: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.cmdb.versions(ciId),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/cmdb/cis/{ci_id}/versions', {
          params: { path: { ci_id: ciId }, query: { cursor: pageParam ?? undefined } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
  });
}

/** The CI as it was at `at` (an ISO instant, UTC), with the relationships live then. */
export function useCiAsOf(ciId: string, at: string | null) {
  return useQuery({
    queryKey: queryKeys.cmdb.asOf(ciId, at ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/cis/{ci_id}/as-of', {
          params: { path: { ci_id: ciId }, query: { at: at ?? '' } },
        }),
      ),
    enabled: at !== null,
    retry: false,
  });
}

/** What changed between two versions: attributes, and relationships added and removed. */
export function useCiCompare(ciId: string, pair: { from: number; to: number } | null) {
  return useQuery({
    queryKey: queryKeys.cmdb.compare(ciId, pair?.from ?? 0, pair?.to ?? 0),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/cis/{ci_id}/compare', {
          params: {
            path: { ci_id: ciId },
            query: { from: pair?.from ?? 1, to: pair?.to ?? 1 },
          },
        }),
      ),
    enabled: pair !== null,
    retry: false,
  });
}

/** Business views whose base CI you may see; `baseCiId`: only those on that CI; `search`: by name. */
export function useBusinessViews({
  baseCiId,
  search = '',
}: { baseCiId?: string; search?: string } = {}) {
  const conditions = [
    ...(baseCiId === undefined ? [] : [{ field: 'base_ci_id', op: 'eq', value: baseCiId }]),
    ...(search.trim() === '' ? [] : [{ field: 'name', op: 'contains', value: search.trim() }]),
  ];
  return useInfiniteQuery({
    queryKey: queryKeys.cmdb.viewList(baseCiId ?? null, search.trim()),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/cmdb/business-views', {
          params: {
            query: {
              filter: conditions.length === 0 ? undefined : JSON.stringify({ and: conditions }),
              sort: 'name',
              limit: 50,
              cursor: pageParam ?? undefined,
              include_total: pageParam === null,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
  });
}

export function useBusinessView(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.cmdb.view(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/business-views/{view_id}', {
          params: { path: { view_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
    retry: false,
  });
}

function useViewSaved() {
  const queryClient = useQueryClient();
  return (saved?: BusinessView) => {
    if (saved !== undefined) queryClient.setQueryData(queryKeys.cmdb.view(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.views, 'list'] });
  };
}

export function useCreateBusinessView() {
  const saved = useViewSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: BusinessViewInput; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/business-views', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateBusinessView() {
  const saved = useViewSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      changes,
      version,
    }: {
      id: string;
      changes: BusinessViewPatch;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/cmdb/business-views/{view_id}', {
          params: { path: { view_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

/** A copy you own, with these changes; the first view stays as it was (REQ-CMDB-009 AC2). */
export function useSaveBusinessViewAsNew() {
  const saved = useViewSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, changes, key }: { id: string; changes: BusinessViewPatch; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/business-views/{view_id}/save-as-new', {
          params: { path: { view_id: id }, header: { 'Idempotency-Key': key } },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

export function useDeleteBusinessView() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/cmdb/business-views/{view_id}', {
          params: { path: { view_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: (_, { id }) => {
      queryClient.removeQueries({ queryKey: queryKeys.cmdb.view(id) });
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.views, 'list'] });
    },
  });
}
