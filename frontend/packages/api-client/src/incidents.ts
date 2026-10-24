import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call, rememberEtag } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';
import type { FilterExpression } from './users';

// Incidents on the work item engine (WP-020, ADR-026). Every write sends If-Match for the version
// the screen was showing; create sends one Idempotency-Key per form so a retry never makes two.
export type Incident = components['schemas']['WorkItemOut'];
export type IncidentListItem = components['schemas']['WorkItemListItem'];
export type IncidentPage = components['schemas']['WorkItemPage'];
export type IncidentInput = components['schemas']['WorkItemIn'];
export type IncidentPatch = Partial<components['schemas']['WorkItemPatch']>;
export type IncidentAction = components['schemas']['WorkItemAction'];
export type IncidentActionState = components['schemas']['WorkItemActionStateOut'];
export type IncidentCatalogue = components['schemas']['WorkItemCatalogueOut'];
export type IncidentCategory = components['schemas']['WorkItemCategoryOut'];
export type IncidentViewCount = components['schemas']['WorkItemViewCountOut'];
export type IncidentAssignee = components['schemas']['WorkItemAssigneeOut'];
export type IncidentHistoryEntry = components['schemas']['WorkItemHistoryEntryOut'];
export type IncidentPerson = components['schemas']['PersonOut'];
export type Priority = components['schemas']['Priority'];
export type Impact = components['schemas']['Impact'];
export type Urgency = components['schemas']['Urgency'];
export type StatusCategory = components['schemas']['StatusCategory'];
export type ReasonList = components['schemas']['ReasonList'];
export type WorkItemChannel = components['schemas']['Channel'];

/** List parameters the UI controls. */
export interface IncidentsQuery {
  view?: string;
  filter?: FilterExpression;
  sort?: string;
  tag?: string;
  limit?: number;
  trash?: boolean;
}

const path = (id: string) => `/api/v1/incidents/${id}`;
const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** One page at a time (cursor-paged); the first page also asks for the (capped) total. */
export function useIncidents(query: IncidentsQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.incidents.list(query),
    queryFn: ({ pageParam }) => {
      const params = {
        query: {
          view: query.trash === true ? undefined : query.view,
          tag: query.tag,
          filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
          sort: query.sort,
          limit: query.limit ?? 50,
          cursor: pageParam ?? undefined,
          include_total: pageParam === null,
        },
      };
      return call(
        query.trash === true
          ? api.GET('/api/v1/incidents/trash', { params })
          : api.GET('/api/v1/incidents', { params }),
      );
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

/** Every built-in view with how many records the user sees in it (capped). */
export function useIncidentViews(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.views,
    queryFn: () => call(api.GET('/api/v1/incidents/views')),
    enabled,
  });
}

/** One incident with its action states; its ETag is remembered for the next write. */
export function useIncident(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.incidents.detail(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/incidents/{record_id}', { params: { path: { record_id: id ?? '' } } })),
    enabled: id !== undefined,
    retry: false, // a 404 (deleted, or out of your reach) is an answer, not a reason to retry
  });
}

/** Every save, newest first; `actors` narrows to people or automation. */
export function useIncidentHistory(
  id: string,
  actors: 'all' | 'people' | 'automation',
  enabled = true,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.incidents.history(id, actors),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/incidents/{record_id}/history', {
          params: { path: { record_id: id }, query: { cursor: pageParam ?? undefined, actors } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
  });
}

/** Statuses, actions, scales, matrix, reasons and the prefix of the tenant. */
export function useIncidentCatalogue(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.catalogue,
    queryFn: () => call(api.GET('/api/v1/incidents/settings')),
    enabled,
    staleTime: 60_000,
  });
}

export function useIncidentCategories(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.categories,
    queryFn: () => call(api.GET('/api/v1/incidents/categories')),
    enabled,
    staleTime: 60_000,
  });
}

/** Technicians of a group (or everyone who can work on incidents), with their open load. */
export function useIncidentAssignees(groupId: string | null, search: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.assignees(groupId, search),
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/assignees', {
          params: {
            query: {
              group_id: groupId ?? undefined,
              search: search === '' ? undefined : search,
              limit: 50,
            },
          },
        }),
      ),
    enabled,
    staleTime: 0,
    placeholderData: (previous) => previous,
  });
}

/** After a write: the record in the cache, lists, views and history refetched, the ETag kept. */
function useSaved() {
  const queryClient = useQueryClient();
  return (saved: Incident) => {
    rememberEtag(path(saved.id), `"${String(saved.version)}"`);
    if (saved.visible) queryClient.setQueryData(queryKeys.incidents.detail(saved.id), saved);
    else queryClient.removeQueries({ queryKey: queryKeys.incidents.detail(saved.id) });
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.incidents.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.views });
    void queryClient.invalidateQueries({
      queryKey: [...queryKeys.incidents.all, 'history', saved.id],
    });
  };
}

export function useCreateIncident() {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true }, // the form shows field errors inline
    mutationFn: ({ body, key }: { body: IncidentInput; key: string }) =>
      call(api.POST('/api/v1/incidents', { params: { header: { 'Idempotency-Key': key } }, body })),
    onSuccess: saved,
  });
}

export function useUpdateIncident(id: string) {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: IncidentPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/incidents/{record_id}', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { confirm_lose_access: false, ...changes },
        }),
      ),
    onSuccess: saved,
  });
}

export function useIncidentAction(id: string) {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      action,
      version,
      reasonCode,
      reasonText,
    }: {
      action: IncidentAction;
      version: number;
      reasonCode?: string;
      reasonText?: string;
    }) => {
      const text = reasonText?.trim() ?? '';
      const body =
        reasonCode === undefined && text === ''
          ? undefined
          : { reason_code: reasonCode ?? null, reason_text: text === '' ? null : text };
      return call(
        api.POST('/api/v1/incidents/{record_id}/actions/{action}', {
          params: { path: { record_id: id, action }, header: ifMatch(version) },
          body,
        }),
      );
    },
    onSuccess: saved,
  });
}

export interface AssignChange {
  version: number;
  groupId: string | null;
  technicianId: string | null;
  reasonCode?: string;
  reasonText?: string;
  confirmLoseAccess?: boolean;
}

export function useAssignIncident(id: string) {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: (change: AssignChange) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/assign', {
          params: { path: { record_id: id }, header: ifMatch(change.version) },
          body: {
            group_id: change.groupId,
            technician_id: change.technicianId,
            reason_code: change.reasonCode ?? null,
            reason_text: change.reasonText?.trim() === '' ? null : (change.reasonText ?? null),
            confirm_lose_access: change.confirmLoseAccess ?? false,
          },
        }),
      ),
    onSuccess: saved,
  });
}

export function useTakeIncident(id: string) {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ version, groupId }: { version: number; groupId?: string }) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/take', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: groupId === undefined ? undefined : { group_id: groupId },
        }),
      ),
    onSuccess: saved,
  });
}

export function useDeleteIncident(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (version: number) =>
      call(
        api.DELETE('/api/v1/incidents/{record_id}', {
          params: { path: { record_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.incidents.detail(id) });
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.incidents.all, 'list'] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.views });
    },
  });
}

export function useRestoreIncident() {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/incidents/{record_id}/restore', {
          params: { path: { record_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: saved,
  });
}
