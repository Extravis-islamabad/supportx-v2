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
export type OnBehalfScope = components['schemas']['OnBehalfScope'];
export type ServiceRequestCatalogue = components['schemas']['WorkItemCatalogueOut'];
export type Approval = components['schemas']['ApprovalOut'];
export type PendingApproval = components['schemas']['PendingApprovalOut'];
export type ApprovalDecision = components['schemas']['DecisionIn'];
export type ServiceRequestViewCount = components['schemas']['WorkItemViewCountOut'];

export interface ServiceRequestsQuery {
  approval_status?: ApprovalStatus;
  catalog_item_id?: string;
  /** A built-in view code from {@link useServiceRequestViews}. */
  view?: string;
  cursor?: string;
}

export const serviceRequestKeys = {
  all: ['service-requests'] as const,
  list: (query: ServiceRequestsQuery) => ['service-requests', 'list', query] as const,
  // Under 'list' so the list channel's refresh updates the view counts too.
  views: ['service-requests', 'list', 'views'] as const,
  detail: (id: string) => ['service-requests', 'detail', id] as const,
  settings: ['service-requests', 'settings'] as const,
  approvals: (id: string) => ['service-requests', 'detail', id, 'approvals'] as const,
  myApprovals: ['service-requests', 'my-approvals'] as const,
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

/** The built-in views (approval views included, REQ-SR-009) with how many requests each holds. */
export function useServiceRequestViews() {
  return useQuery({
    queryKey: serviceRequestKeys.views,
    queryFn: () => call(api.GET('/api/v1/service-requests/views')),
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

/** The service request type's settings (statuses, prefix, whom requesters may raise for). */
export function useServiceRequestCatalogue(enabled = true) {
  return useQuery({
    queryKey: serviceRequestKeys.settings,
    queryFn: () => call(api.GET('/api/v1/service-requests/settings')),
    enabled,
    staleTime: 60_000,
  });
}

/**
 * Change service request settings with If-Match on the version the screen showed; the answer
 * replaces the cached settings at once, other screens follow `work_items.settings_changed`.
 */
export function useServiceRequestSettingsChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      body,
      version,
    }: {
      body: Partial<components['schemas']['WorkItemSettingsPatch']>;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/service-requests/settings', {
          params: { header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: (catalogue) => {
      queryClient.setQueryData(serviceRequestKeys.settings, catalogue);
    },
  });
}

/** A request's approvals (REQ-SR-024): for those who see it and for its approvers. */
export function useApprovals(recordId: string) {
  return useQuery({
    queryKey: serviceRequestKeys.approvals(recordId),
    queryFn: () =>
      call(
        api.GET('/api/v1/service-requests/{record_id}/approvals', {
          params: { path: { record_id: recordId } },
        }),
      ),
    enabled: recordId !== '',
  });
}

/** The approvals waiting for the signed-in person (the header drawer, REQ-SR-025). */
export function useMyApprovals() {
  return useQuery({
    queryKey: serviceRequestKeys.myApprovals,
    queryFn: () => call(api.GET('/api/v1/service-requests/my-approvals')),
  });
}

/** The approvals you decided in the last 30 days, newest first (WP-032 D6). */
export function useMyDecidedApprovals() {
  return useQuery({
    queryKey: [...serviceRequestKeys.myApprovals, 'decided'],
    queryFn: () => call(api.GET('/api/v1/service-requests/my-approvals/decided')),
  });
}

/** Approve several at once with one comment (≤ 20, approve only); each outcome comes back. */
export function useApproveMany() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (body: {
      items: { record_id: string; approval_id: string; version: number }[];
      comment: string | null;
    }) => call(api.POST('/api/v1/service-requests/approvals/decisions', { body })),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.myApprovals });
    },
  });
}

/** Approve or reject with If-Match on the approval's version; the first decision decides. */
export function useDecideApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      recordId,
      approvalId,
      version,
      body,
    }: {
      recordId: string;
      approvalId: string;
      version: number;
      body: ApprovalDecision;
    }) =>
      call(
        api.POST('/api/v1/service-requests/{record_id}/approvals/{approval_id}/decision', {
          params: {
            path: { record_id: recordId, approval_id: approvalId },
            header: { 'If-Match': `"${String(version)}"` },
          },
          body,
        }),
      ),
    onSettled: (_data, _error, { recordId }) => {
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.detail(recordId) });
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.myApprovals });
    },
  });
}

/** The requester withdraws a request awaiting approval (REQ-SR-061). */
export function useWithdrawRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ recordId, version }: { recordId: string; version: number }) =>
      call(
        api.POST('/api/v1/service-requests/{record_id}/withdraw', {
          params: {
            path: { record_id: recordId },
            header: { 'If-Match': `"${String(version)}"` },
          },
        }),
      ),
    onSettled: (_data, _error, { recordId }) => {
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.detail(recordId) });
    },
  });
}

/** What a signed action link would do (WP-030 s3): never acts; the token goes in the body. */
export function usePeekActionLink(token: string | undefined) {
  return useQuery({
    queryKey: ['action-links', 'peek', token ?? ''],
    queryFn: () => call(api.POST('/api/v1/action-links/peek', { body: { token: token ?? '' } })),
    enabled: token !== undefined && token !== '',
    retry: false,
    staleTime: Infinity,
    meta: { silent: true }, // the page says why a link does nothing
  });
}

/** Take a signed action link's action, once. */
export function useActionLink() {
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ token, body }: { token: string; body: Record<string, unknown> }) =>
      call(api.POST('/api/v1/action-links/use', { body: { token, body } })),
  });
}

export type RequestTask = components['schemas']['WorkItemTaskOut'];

/** A request's tasks, its fulfilment plan's first (WP-030 s3). Under the record's key: live. */
export function useRequestTasks(recordId: string) {
  return useQuery({
    queryKey: [...serviceRequestKeys.detail(recordId), 'tasks'] as const,
    queryFn: () =>
      call(
        api.GET('/api/v1/service-requests/{record_id}/tasks', {
          params: { path: { record_id: recordId } },
        }),
      ),
    enabled: recordId !== '',
  });
}

/** Set a task's status with If-Match; the last required plan task done may fulfil it. */
export function useRequestTaskStatus(recordId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ task, status }: { task: RequestTask; status: RequestTask['status'] }) =>
      call(
        api.PATCH('/api/v1/service-requests/{record_id}/tasks/{task_id}', {
          params: {
            path: { record_id: recordId, task_id: task.id },
            header: { 'If-Match': `"${String(task.version)}"` },
          },
          body: { status },
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: serviceRequestKeys.detail(recordId) });
    },
  });
}

/**
 * An e-mailed link without sign-in (D-132): what it would do; never acts. `tenant` is the
 * link's `?t=` slug, for addresses that name no tenant.
 */
export function usePublicPeekActionLink(token: string | undefined, tenant?: string | null) {
  return useQuery({
    queryKey: ['action-links', 'public-peek', token ?? '', tenant ?? ''],
    queryFn: () =>
      call(
        api.POST('/api/v1/public/action-links/peek', {
          body: { token: token ?? '', tenant: tenant ?? null },
        }),
      ),
    enabled: token !== undefined && token !== '',
    retry: false,
    staleTime: Infinity,
    meta: { silent: true }, // the page says why a link does nothing
  });
}

/** Take an e-mailed link's action without sign-in, once (D-132). */
export function usePublicActionLink() {
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      token,
      tenant,
      body,
    }: {
      token: string;
      tenant?: string | null;
      body: Record<string, unknown>;
    }) =>
      call(
        api.POST('/api/v1/public/action-links/use', {
          body: { token, tenant: tenant ?? null, body },
        }),
      ),
  });
}
