import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { useSingleFlight } from './incidents';
import type { components } from './schema';

// Service requests and the catalog they come from (WP-030). A service request is a work item of
// its own type; this file covers what the console needs before its full record page: the
// catalog, the list, raising one from an item, and one record.
export type CatalogItem = components['schemas']['CatalogItemOut'];
export type CatalogCategory = components['schemas']['CategoryOut'];
export type CatalogQuestion = components['schemas']['QuestionIO'];
export type ServiceRequest = components['schemas']['WorkItemOut'];
export type ServiceRequestInput = components['schemas']['WorkItemIn'];
export type ApprovalStatus = components['schemas']['ApprovalStatus'];

export interface ServiceRequestsQuery {
  approval_status?: ApprovalStatus;
  catalog_item_id?: string;
  cursor?: string;
}

export const serviceRequestKeys = {
  all: ['service-requests'] as const,
  list: (query: ServiceRequestsQuery) => ['service-requests', 'list', query] as const,
  detail: (id: string) => ['service-requests', 'detail', id] as const,
  catalog: ['catalog'] as const,
  items: ['catalog', 'items'] as const,
  item: (id: string) => ['catalog', 'items', id] as const,
  categories: ['catalog', 'categories'] as const,
};

/** The items the signed-in person may raise (staff: every item, disabled ones marked). */
export function useCatalogItems() {
  return useQuery({
    queryKey: serviceRequestKeys.items,
    queryFn: () => call(api.GET('/api/v1/catalog/items')),
  });
}

export function useCatalogItem(id: string | undefined) {
  return useQuery({
    queryKey: serviceRequestKeys.item(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/catalog/items/{item_id}', { params: { path: { item_id: id ?? '' } } })),
    enabled: id !== undefined && id !== '',
  });
}

export function useCatalogCategories() {
  return useQuery({
    queryKey: serviceRequestKeys.categories,
    queryFn: () => call(api.GET('/api/v1/catalog/categories')),
    staleTime: 60_000,
  });
}

export function useServiceRequests(query: ServiceRequestsQuery) {
  return useQuery({
    queryKey: serviceRequestKeys.list(query),
    queryFn: () => call(api.GET('/api/v1/service-requests', { params: { query } })),
    placeholderData: keepPreviousData,
  });
}

export function useServiceRequest(id: string) {
  return useQuery({
    queryKey: serviceRequestKeys.detail(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/service-requests/{record_id}', { params: { path: { record_id: id } } }),
      ),
  });
}

/** Raise a request from an item. One Idempotency-Key per form, so a retry never makes two. */
export function useRaiseServiceRequest() {
  const queryClient = useQueryClient();
  const once = useSingleFlight(({ body, key }: { body: ServiceRequestInput; key: string }) =>
    call(
      api.POST('/api/v1/service-requests', {
        params: { header: { 'Idempotency-Key': key } },
        body,
      }),
    ),
  );
  return useMutation({
    mutationFn: once,
    onSuccess: (made) => {
      queryClient.setQueryData(serviceRequestKeys.detail(made.id), made);
      void queryClient.invalidateQueries({ queryKey: [...serviceRequestKeys.all, 'list'] });
    },
  });
}
