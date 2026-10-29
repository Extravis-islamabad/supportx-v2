import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { IncidentsQuery } from './incidents';
import { queryKeys } from './keys';
import type { components } from './schema';

// Saved views, list settings and bulk jobs of the incident list (WP-020d; REQ-INC-104, 106, 110,
// 119, 120).

export type IncidentListField = components['schemas']['ListFieldOut'];
export type IncidentViewFilter = components['schemas']['ViewFilterOut'];
export type SavedView = components['schemas']['SavedViewOut'];
export type SavedViewInput = components['schemas']['SavedViewIn'];
export type ListColumn = components['schemas']['ListColumn'];
export type ListSetting = components['schemas']['ListSettingOut'];
export type ListSettingInput = components['schemas']['ListSettingIn'];
export type BulkAction = components['schemas']['BulkAction'];
export type BulkJob = components['schemas']['BulkJobOut'];
export type BulkResult = components['schemas']['BulkResultOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Every field the list filters, sorts or shows, with the tenant's custom fields. */
export function useIncidentListFields(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.listFields,
    queryFn: () => call(api.GET('/api/v1/incidents/list-fields')),
    enabled,
    staleTime: 60_000,
  });
}

/** Each built-in view as a filter (for the export, which takes a filter and not a view). */
export function useIncidentViewFilters(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.viewFilters,
    queryFn: () => call(api.GET('/api/v1/incidents/view-filters')),
    enabled,
  });
}

/** Your saved views and the shared ones, by name. */
export function useSavedViews(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.savedViews,
    queryFn: () => call(api.GET('/api/v1/incidents/saved-views')),
    enabled,
  });
}

export type SavedViewChange =
  | { kind: 'create'; view: SavedViewInput }
  | { kind: 'update'; id: string; version: number; view: Partial<SavedViewInput> }
  | { kind: 'delete'; id: string; version: number };

/** Save, change or remove one of your views. */
export function useSavedViewChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: SavedViewChange): Promise<SavedView | null> => {
      if (change.kind === 'create') {
        return call(api.POST('/api/v1/incidents/saved-views', { body: change.view }));
      }
      if (change.kind === 'update') {
        return call(
          api.PATCH('/api/v1/incidents/saved-views/{view_id}', {
            params: { path: { view_id: change.id }, header: ifMatch(change.version) },
            body: change.view,
          }),
        );
      }
      await call(
        api.DELETE('/api/v1/incidents/saved-views/{view_id}', {
          params: { path: { view_id: change.id }, header: ifMatch(change.version) },
        }),
      );
      return null;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.savedViews });
    },
  });
}

/** Your columns, sort and page size for one view (`version` null: the defaults). */
export function useListSetting(viewKey: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.listSetting(viewKey),
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/list-settings/{view_key}', {
          params: { path: { view_key: viewKey } },
        }),
      ),
    enabled,
  });
}

/** Save your settings for one view; the first save has no version. */
export function useSaveListSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      viewKey,
      version,
      setting,
    }: {
      viewKey: string;
      version: number | null;
      setting: ListSettingInput;
    }) =>
      call(
        api.PUT('/api/v1/incidents/list-settings/{view_key}', {
          params: {
            path: { view_key: viewKey },
            header: version === null ? {} : ifMatch(version),
          },
          body: setting,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.incidents.listSetting(saved.view_key), saved);
    },
  });
}

/** What a bulk job is asked for: picked rows, or every record of the list as shown. */
export interface BulkRequest {
  action: BulkAction;
  changes: Record<string, unknown>;
  /** Picked rows; leave out for "all matching" (the list query below decides). */
  recordIds?: string[];
  /** The list's own query, for "all matching". */
  query?: Pick<IncidentsQuery, 'view' | 'filter' | 'tag'>;
}

/** Queue a bulk job; progress arrives on your channel. */
export function useStartBulk() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: BulkRequest) =>
      call(
        api.POST('/api/v1/incidents/bulk', {
          params: {
            query:
              request.recordIds === undefined
                ? {
                    view: request.query?.view,
                    tag: request.query?.tag,
                    filter:
                      request.query?.filter === undefined
                        ? undefined
                        : JSON.stringify(request.query.filter),
                  }
                : {},
          },
          body: {
            action: request.action,
            changes: request.changes,
            record_ids: request.recordIds ?? [],
            all_matching: request.recordIds === undefined,
          },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(queryKeys.incidents.bulkJob(job.id), job);
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.bulkJobs });
    },
  });
}

/** One of your bulk jobs with its per-record results. */
export function useBulkJob(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.incidents.bulkJob(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/incidents/bulk-jobs/{job_id}', { params: { path: { job_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** Your latest bulk jobs, newest first (without results). */
export function useBulkJobs(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.bulkJobs,
    queryFn: () => call(api.GET('/api/v1/incidents/bulk-jobs')),
    enabled,
  });
}
