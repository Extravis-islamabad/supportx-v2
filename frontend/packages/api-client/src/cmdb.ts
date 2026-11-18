import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call, rememberEtag } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';
import type { FilterExpression } from './users';

// The CMDB (WP-053 S1): CI types, states, settings and configuration items.
export type CiType = components['schemas']['CiTypeOut'];
export type CiTypeInput = components['schemas']['CiTypeIn'];
export type CiTypePatch = components['schemas']['CiTypePatch'];
export type CiState = components['schemas']['CiStateOut'];
export type CiStateInput = components['schemas']['CiStateIn'];
export type CiStatePatch = components['schemas']['CiStatePatch'];
export type Ci = components['schemas']['CiOut'];
export type CiListItem = components['schemas']['CiListItem'];
export type CiInput = components['schemas']['CiIn'];
export type CiPatch = components['schemas']['CiPatch'];
export type CiHistoryEntry = components['schemas']['CiHistoryEntryOut'];
export type CmdbSettings = components['schemas']['CmdbSettingsOut'];
export type CiFromAssetsResult = components['schemas']['CiFromAssetsOut'];

/** List parameters the UI controls: the filter DSL, a sort, a type (and below), the trash. */
export interface CisQuery {
  filter?: FilterExpression;
  sort?: string;
  limit?: number;
  typeTree?: string;
  trash?: boolean;
}

const ciPath = (id: string) => `/api/v1/cmdb/cis/${id}`;
const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export function useCiTypes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.types,
    queryFn: () => call(api.GET('/api/v1/cmdb/ci-types')),
    enabled,
  });
}

export function useCiStates(enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.states,
    queryFn: () => call(api.GET('/api/v1/cmdb/ci-states')),
    enabled,
  });
}

export function useCmdbSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.settings,
    queryFn: () => call(api.GET('/api/v1/cmdb/settings')),
    enabled,
  });
}

/** CIs you may see (or the trash), cursor-paged. */
export function useCis(query: CisQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.cmdb.list(query),
    queryFn: ({ pageParam }) => {
      const params = {
        query: {
          filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
          sort: query.sort,
          limit: query.limit ?? 50,
          cursor: pageParam ?? undefined,
          include_total: pageParam === null,
        },
      };
      return call(
        query.trash === true
          ? api.GET('/api/v1/cmdb/cis/trash', { params })
          : api.GET('/api/v1/cmdb/cis', {
              params: { query: { ...params.query, type_tree: query.typeTree } },
            }),
      );
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

export function useCi(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.cmdb.detail(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/cmdb/cis/{ci_id}', { params: { path: { ci_id: id ?? '' } } })),
    enabled: id !== undefined,
    retry: false,
  });
}

export function useCiHistory(id: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.cmdb.history(id),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/cmdb/cis/{ci_id}/history', {
          params: { path: { ci_id: id }, query: { cursor: pageParam ?? undefined } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
  });
}

/** CIs to choose from (end-of-life ones left out when the tenant says so). */
export function useCiPicker(search: string, typeId?: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.picker(search, typeId ?? null),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/cis/picker', {
          params: { query: { search: search === '' ? undefined : search, type_id: typeId } },
        }),
      ),
    enabled,
    placeholderData: (previous) => previous,
  });
}

function useCiSaved() {
  const queryClient = useQueryClient();
  return (saved: Ci) => {
    rememberEtag(ciPath(saved.id), `"${String(saved.version)}"`);
    queryClient.setQueryData(queryKeys.cmdb.detail(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.history(saved.id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.types });
  };
}

/** Create a CI; `key` is the form's Idempotency-Key (a retried save returns the first CI). */
export function useCreateCi() {
  const saved = useCiSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: CiInput; key: string }) =>
      call(api.POST('/api/v1/cmdb/cis', { params: { header: { 'Idempotency-Key': key } }, body })),
    onSuccess: saved,
  });
}

export function useUpdateCi(id: string) {
  const saved = useCiSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: CiPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/cmdb/cis/{ci_id}', {
          params: { path: { ci_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

export function useCopyCi(id: string) {
  const saved = useCiSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: (key: string) =>
      call(
        api.POST('/api/v1/cmdb/cis/{ci_id}/copy', {
          params: { path: { ci_id: id }, header: { 'Idempotency-Key': key } },
        }),
      ),
    onSuccess: saved,
  });
}

export type CiTypeChangePreview = components['schemas']['CiTypeChangePreviewOut'];

/**
 * What moving the CI to `typeId` would drop (0175 part 2): the custom fields outside the new
 * type's, by name, and whether a field access rule blocks it. Nothing changes.
 */
export function useCiTypeChangePreview(id: string, typeId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.cmdb.typeChangePreview(id, typeId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/cis/{ci_id}/change-type-preview', {
          params: { path: { ci_id: id }, query: { type_id: typeId ?? '' } },
        }),
      ),
    enabled: typeId !== undefined,
  });
}

export function useChangeCiType(id: string) {
  const saved = useCiSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      typeId,
      version,
      confirmDropped = false,
    }: {
      typeId: string;
      version: number;
      /** Drop the values the new type's fields do not include (shown by the preview first). */
      confirmDropped?: boolean;
    }) =>
      call(
        api.POST('/api/v1/cmdb/cis/{ci_id}/change-type', {
          params: { path: { ci_id: id }, header: ifMatch(version) },
          body: { type_id: typeId, confirm_dropped_fields: confirmDropped },
        }),
      ),
    onSuccess: saved,
  });
}

export function useDeleteCi(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (version: number) =>
      call(
        api.DELETE('/api/v1/cmdb/cis/{ci_id}', {
          params: { path: { ci_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.detail(id) });
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.cmdb.all, 'list'] });
    },
  });
}

export function useRestoreCi() {
  const saved = useCiSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/cmdb/cis/{ci_id}/restore', {
          params: { path: { ci_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: saved,
  });
}

/** Types, states and settings changed: the tree, the forms and the lists refetch. */
function useConfigSaved() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.all });
  };
}

export function useCreateCiType() {
  const saved = useConfigSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: CiTypeInput; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/ci-types', { params: { header: { 'Idempotency-Key': key } }, body }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateCiType() {
  const saved = useConfigSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, changes, version }: { id: string; changes: CiTypePatch; version: number }) =>
      call(
        api.PATCH('/api/v1/cmdb/ci-types/{type_id}', {
          params: { path: { type_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

export function useDeleteCiType() {
  const saved = useConfigSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/cmdb/ci-types/{type_id}', {
          params: { path: { type_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: saved,
  });
}

export function useCreateCiState() {
  const saved = useConfigSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: CiStateInput; key: string }) =>
      call(
        api.POST('/api/v1/cmdb/ci-states', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateCiState() {
  const saved = useConfigSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      changes,
      version,
    }: {
      id: string;
      changes: CiStatePatch;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/cmdb/ci-states/{state_id}', {
          params: { path: { state_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

export function useDeleteCiState() {
  const saved = useConfigSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/cmdb/ci-states/{state_id}', {
          params: { path: { state_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateCmdbSettings() {
  const saved = useConfigSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ excludeEol, version }: { excludeEol: boolean; version: number }) =>
      call(
        api.PUT('/api/v1/cmdb/settings', {
          params: { header: ifMatch(version) },
          body: { exclude_eol_from_pickers: excludeEol },
        }),
      ),
    onSuccess: saved,
  });
}
