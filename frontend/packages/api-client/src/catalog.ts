import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';
import { serviceRequestKeys } from './serviceRequests';

// The service catalog's administration (WP-031): categories in a tree, items with a life (draft,
// published, retired, planned), copy and delete, search, the tenant's catalog settings and the
// starter catalog (D-138). Every write sends If-Match (or an Idempotency-Key for a create); the
// answer replaces the cached record at once, and every other screen follows the tenant's
// `service_catalog.changed` broadcast (ConsoleLayout, PortalLayout).

export type CatalogItemInput = components['schemas']['CatalogItemIn'];
export type CatalogCategoryInput = components['schemas']['CategoryIn'];
export type CatalogCategoryPatch = components['schemas']['CategoryPatchIn'];
export type CatalogItemStatus = components['schemas']['ItemStatus'];
export type CatalogItemKind = components['schemas']['ItemKind'];
export type CatalogQuestionKind = components['schemas']['QuestionKind'];
export type CatalogQuestionAudience = components['schemas']['QuestionAudience'];
export type CatalogSettings = components['schemas']['CatalogSettingsOut'];
export type CatalogStarter = components['schemas']['CatalogStarterOut'];
export type CatalogStarterPublished = components['schemas']['CatalogStarterPublishOut'];

export const catalogKeys = {
  all: serviceRequestKeys.catalog,
  items: serviceRequestKeys.items,
  list: (query: CatalogItemsQuery) => [...serviceRequestKeys.items, 'list', query] as const,
  search: (q: string) => [...serviceRequestKeys.items, 'search', q] as const,
  item: serviceRequestKeys.item,
  categories: serviceRequestKeys.categories,
  settings: ['catalog', 'settings'] as const,
  starter: ['catalog', 'starter'] as const,
};

export interface CatalogItemsQuery {
  category_id?: string;
  status?: CatalogItemStatus[];
  featured?: boolean;
}

/** Items the viewer may see, narrowed (staff: any status; others: published, open to them). */
export function useCatalogItemList(query: CatalogItemsQuery, enabled = true) {
  return useQuery({
    queryKey: catalogKeys.list(query),
    queryFn: () => call(api.GET('/api/v1/catalog/items', { params: { query } })),
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Search the items the viewer may see (names, keywords, texts, typos; best first). */
export function useCatalogSearch(q: string) {
  const text = q.trim();
  return useQuery({
    queryKey: catalogKeys.search(text),
    queryFn: () =>
      call(api.GET('/api/v1/catalog/items/search', { params: { query: { q: text } } })),
    enabled: text.length > 0,
    placeholderData: keepPreviousData,
  });
}

/** Add an item (a draft unless `status` is published). One Idempotency-Key per form. */
export function useCreateCatalogItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: CatalogItemInput; key: string }) =>
      call(
        api.POST('/api/v1/catalog/items', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: (made) => {
      queryClient.setQueryData(catalogKeys.item(made.id), made);
      void queryClient.invalidateQueries({ queryKey: catalogKeys.items });
    },
  });
}

/** Change, publish or retire an item, with If-Match on the version shown. */
export function useUpdateCatalogItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body, version }: { id: string; body: CatalogItemInput; version: number }) =>
      call(
        api.PATCH('/api/v1/catalog/items/{item_id}', {
          params: { path: { item_id: id }, header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: (item) => {
      queryClient.setQueryData(catalogKeys.item(item.id), item);
      void queryClient.invalidateQueries({ queryKey: [...catalogKeys.items, 'list'] });
      void queryClient.invalidateQueries({ queryKey: catalogKeys.starter });
    },
  });
}

/** An independent draft copy ("Copy of …"). */
export function useCopyCatalogItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, key }: { id: string; key: string }) =>
      call(
        api.POST('/api/v1/catalog/items/{item_id}/copy', {
          params: { path: { item_id: id }, header: { 'Idempotency-Key': key } },
        }),
      ),
    onSuccess: (made) => {
      queryClient.setQueryData(catalogKeys.item(made.id), made);
      void queryClient.invalidateQueries({ queryKey: catalogKeys.items });
    },
  });
}

/** Delete an item no request names (409 `catalog_item_in_use` otherwise: retire it). */
export function useDeleteCatalogItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/catalog/items/{item_id}', {
          params: { path: { item_id: id }, header: { 'If-Match': `"${String(version)}"` } },
        }),
      ),
    onSuccess: (_, { id }) => {
      queryClient.removeQueries({ queryKey: catalogKeys.item(id) });
      void queryClient.invalidateQueries({ queryKey: catalogKeys.items });
    },
  });
}

export function useCreateCatalogCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ body, key }: { body: CatalogCategoryInput; key: string }) =>
      call(
        api.POST('/api/v1/catalog/categories', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: catalogKeys.categories });
    },
  });
}

export function useUpdateCatalogCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      body,
      version,
    }: {
      id: string;
      body: CatalogCategoryPatch;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/catalog/categories/{category_id}', {
          params: {
            path: { category_id: id },
            header: { 'If-Match': `"${String(version)}"` },
          },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: catalogKeys.categories });
      void queryClient.invalidateQueries({ queryKey: catalogKeys.items });
    },
  });
}

/** Delete an empty category (409 `service_category_in_use` with the counts otherwise). */
export function useDeleteCatalogCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/catalog/categories/{category_id}', {
          params: {
            path: { category_id: id },
            header: { 'If-Match': `"${String(version)}"` },
          },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: catalogKeys.categories });
    },
  });
}

/** The tenant's catalog settings (reading never writes; the defaults before the first change). */
export function useCatalogSettings() {
  return useQuery({
    queryKey: catalogKeys.settings,
    queryFn: () => call(api.GET('/api/v1/catalog/settings')),
    staleTime: 60_000,
  });
}

export function useCatalogSettingsChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      body,
      version,
    }: {
      body: components['schemas']['CatalogSettingsIn'];
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/catalog/settings', {
          params: { header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: (settings) => {
      queryClient.setQueryData(catalogKeys.settings, settings);
    },
  });
}

/** How many starter items (D-138) are still drafts waiting for a group. */
export function useCatalogStarter(enabled = true) {
  return useQuery({
    queryKey: catalogKeys.starter,
    queryFn: () => call(api.GET('/api/v1/catalog/starter')),
    enabled,
  });
}

/** Give the starter drafts a fulfilment group and publish those whose checks pass. */
export function usePublishCatalogStarter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (groupId: string) =>
      call(api.POST('/api/v1/catalog/starter/publish', { body: { group_id: groupId } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: catalogKeys.all });
    },
  });
}
