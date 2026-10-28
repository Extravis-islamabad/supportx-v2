import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef } from 'react';

import { api, call, rememberEtag } from './client';
import { ApiError } from './errors';
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
export type IncidentSearchResult = components['schemas']['WorkItemSearchOut'];
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

/** Search parameters (GET /incidents/search, WP-027). */
export interface IncidentSearchQuery {
  /** Display ID, words, or the requester's name or email. Empty: most recently updated. */
  q?: string;
  /** Only these records (recently viewed), in the user's scope. */
  ids?: string[];
  requesterId?: string;
  statusCategories?: StatusCategory[];
  limit?: number;
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
    // The page shows its own "not found" (deleted, handed over); never a second error toast
    // on top of "Moved to the trash" (QA BUG-08).
    meta: { silent: true },
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

/**
 * Incidents the user may see, best match first: exactly the records the lists show (D-052).
 * Kept under the list key, so every list refresh (realtime, saves) refreshes searches too.
 */
export function useIncidentSearch(query: IncidentSearchQuery, enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.search(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/search', {
          params: {
            query: {
              q: query.q === undefined || query.q.trim() === '' ? undefined : query.q.trim(),
              ids: query.ids,
              requester_id: query.requesterId,
              status_category: query.statusCategories,
              limit: query.limit ?? 20,
            },
          },
        }),
      ),
    enabled: enabled && (query.ids === undefined || query.ids.length > 0),
    staleTime: 0,
    placeholderData: (previous) => previous,
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

/**
 * One request at a time per hook (QA BUG-02): a double-click, or Enter plus a click, while a
 * write is on its way joins that write instead of sending a second one with the old version
 * (which the server would refuse as a conflict). Buttons are disabled while pending too; this
 * covers the clicks that arrive before the screen re-renders.
 */
export function useSingleFlight<A, R>(run: (args: A) => Promise<R>): (args: A) => Promise<R> {
  const flight = useRef<Promise<R> | null>(null);
  return (args: A) => {
    if (flight.current !== null) return flight.current;
    const started = run(args).finally(() => {
      flight.current = null;
    });
    flight.current = started;
    return started;
  };
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

/**
 * A stale change (409): fetch the saved incident, so the conflict dialog compares the version
 * shown with the one saved now (QA WP-029 BUG-05).
 */
function useRefreshOnConflict(id: string) {
  const queryClient = useQueryClient();
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.detail(id) });
    }
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
  const once = useSingleFlight(
    ({ changes, version }: { changes: IncidentPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/incidents/{record_id}', {
          params: { path: { record_id: id }, header: ifMatch(version) },
          body: { confirm_lose_access: false, ...changes },
        }),
      ),
  );
  return useMutation({ meta: { silent: true }, mutationFn: once, onSuccess: saved });
}

export interface ActionRun {
  action: IncidentAction;
  version: number;
  reasonCode?: string;
  reasonText?: string;
  /** Start work on an unassigned incident: which of your groups (QA BUG-05). */
  groupId?: string;
}

export function useIncidentAction(id: string) {
  const saved = useSaved();
  const refresh = useRefreshOnConflict(id);
  const once = useSingleFlight(
    ({ action, version, reasonCode, reasonText, groupId }: ActionRun) => {
      const text = reasonText?.trim() ?? '';
      const body =
        reasonCode === undefined && text === '' && groupId === undefined
          ? undefined
          : {
              reason_code: reasonCode ?? null,
              reason_text: text === '' ? null : text,
              ...(groupId === undefined ? {} : { group_id: groupId }),
            };
      return call(
        api.POST('/api/v1/incidents/{record_id}/actions/{action}', {
          params: { path: { record_id: id, action }, header: ifMatch(version) },
          body,
        }),
      );
    },
  );
  return useMutation({
    meta: { silent: true },
    mutationFn: once,
    onSuccess: saved,
    onError: refresh,
  });
}

export interface AssignChange {
  version: number;
  groupId: string | null;
  technicianId: string | null;
  reasonCode?: string;
  reasonText?: string;
  confirmLoseAccess?: boolean;
  /** With confirmLoseAccess: keep following it (D-068); undefined: the tenant default. */
  keepFollowing?: boolean;
}

export function useAssignIncident(id: string) {
  const saved = useSaved();
  const refresh = useRefreshOnConflict(id);
  const once = useSingleFlight((change: AssignChange) =>
    call(
      api.POST('/api/v1/incidents/{record_id}/assign', {
        params: { path: { record_id: id }, header: ifMatch(change.version) },
        body: {
          group_id: change.groupId,
          technician_id: change.technicianId,
          reason_code: change.reasonCode ?? null,
          reason_text: change.reasonText?.trim() === '' ? null : (change.reasonText ?? null),
          confirm_lose_access: change.confirmLoseAccess ?? false,
          keep_following: change.keepFollowing ?? null,
        },
      }),
    ),
  );
  return useMutation({
    meta: { silent: true },
    mutationFn: once,
    onSuccess: saved,
    onError: refresh,
  });
}

export function useTakeIncident(id: string) {
  const saved = useSaved();
  const refresh = useRefreshOnConflict(id);
  const once = useSingleFlight(({ version, groupId }: { version: number; groupId?: string }) =>
    call(
      api.POST('/api/v1/incidents/{record_id}/take', {
        params: { path: { record_id: id }, header: ifMatch(version) },
        body: groupId === undefined ? undefined : { group_id: groupId },
      }),
    ),
  );
  return useMutation({
    meta: { silent: true },
    mutationFn: once,
    onSuccess: saved,
    onError: refresh,
  });
}

export function useDeleteIncident(id: string) {
  const queryClient = useQueryClient();
  const once = useSingleFlight((version: number) =>
    call(
      api.DELETE('/api/v1/incidents/{record_id}', {
        params: { path: { record_id: id }, header: ifMatch(version) },
      }),
    ),
  );
  return useMutation({
    meta: { silent: true },
    mutationFn: once,
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.incidents.detail(id) });
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.incidents.all, 'list'] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.views });
    },
  });
}

export function useRestoreIncident() {
  const saved = useSaved();
  const once = useSingleFlight(({ id, version }: { id: string; version: number }) =>
    call(
      api.POST('/api/v1/incidents/{record_id}/restore', {
        params: { path: { record_id: id }, header: ifMatch(version) },
      }),
    ),
  );
  return useMutation({ meta: { silent: true }, mutationFn: once, onSuccess: saved });
}
