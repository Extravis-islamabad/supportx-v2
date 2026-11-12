import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

// Assets linked to incidents and requests (REQ-AST-025): the record's list, link and unlink, and
// the asset picker of the forms (lane B's `/assets/picker`, the person's own first).

export type RecordAsset = components['schemas']['WorkItemAssetOut'];
export type PickedAsset = components['schemas']['PickedAssetOut'];
/** The two record types that link assets, by their route prefix. */
export type AssetBase = 'incidents' | 'service-requests';

/** Under the record's detail key: realtime and every refresh of the record cover it (rule 5c). */
export const recordAssetKeys = {
  of: (base: AssetBase, id: string) => [base, 'detail', id, 'assets'] as const,
  picker: (q: string, forUser: string | null) => ['assets', 'picker', q, forUser] as const,
};

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export function useRecordAssets(base: AssetBase, id: string, enabled = true) {
  return useQuery({
    queryKey: recordAssetKeys.of(base, id),
    queryFn: () =>
      base === 'incidents'
        ? call(
            api.GET('/api/v1/incidents/{record_id}/assets', {
              params: { path: { record_id: id } },
            }),
          )
        : call(
            api.GET('/api/v1/service-requests/{record_id}/assets', {
              params: { path: { record_id: id } },
            }),
          ),
    enabled,
    // A side panel: the record page already reports a record it cannot load.
    meta: { silent: true },
  });
}

/** The picker: the person's (or `forUser`'s) own assets first, then, for staff, a search. */
export function useAssetPicker(q: string, forUser: string | null, enabled = true) {
  return useQuery({
    queryKey: recordAssetKeys.picker(q, forUser),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/picker', {
          params: { query: { q: q === '' ? undefined : q, for_user: forUser ?? undefined } },
        }),
      ),
    enabled,
    staleTime: 30_000,
    // A form field: a failure shows as an empty list, never a toast over the form.
    meta: { silent: true },
  });
}

/** The paged picker's filters (REQ-AST-046): part of any identifier, a tree node, a site. */
export interface AssetPickerQuery {
  q: string;
  productTypeId?: string;
  siteId?: string;
}

/** Assets to pick, by name, a page at a time; staff search their scope, others what they hold. */
export function useAssetPickerPage(query: AssetPickerQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: ['assets', 'picker', 'search', query] as const,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/assets/picker/search', {
          params: {
            query: {
              q: query.q === '' ? undefined : query.q,
              product_type_id: query.productTypeId,
              site_id: query.siteId,
              cursor: pageParam ?? undefined,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
    staleTime: 30_000,
    meta: { silent: true },
  });
}

export function useLinkAssets(base: AssetBase, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ assetIds, key }: { assetIds: string[]; key: string }) => {
      const params = {
        path: { record_id: id },
        header: { 'Idempotency-Key': key },
      };
      const body = { asset_ids: assetIds };
      return base === 'incidents'
        ? call(api.POST('/api/v1/incidents/{record_id}/assets', { params, body }))
        : call(api.POST('/api/v1/service-requests/{record_id}/assets', { params, body }));
    },
    onSuccess: (found) => {
      queryClient.setQueryData(recordAssetKeys.of(base, id), found);
    },
  });
}

export function useUnlinkAsset(base: AssetBase, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ link }: { link: RecordAsset }) => {
      const params = { path: { record_id: id, link_id: link.id }, header: ifMatch(link.version) };
      return base === 'incidents'
        ? call(api.DELETE('/api/v1/incidents/{record_id}/assets/{link_id}', { params }))
        : call(api.DELETE('/api/v1/service-requests/{record_id}/assets/{link_id}', { params }));
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: recordAssetKeys.of(base, id) });
    },
  });
}
