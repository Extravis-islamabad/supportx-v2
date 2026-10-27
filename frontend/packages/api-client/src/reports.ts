import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Reports (WP-035, ADR-033). A run is a POST (the definition is a JSON body) but reads only, so
// it is a query keyed by the definition: the same report shown twice is fetched once, and list
// signals refresh it live (`queryKeys.reports.runs`).
export type ReportDefinition = components['schemas']['ReportDefinition-Input'];
export type ReportResult = components['schemas']['ReportResultOut'];
export type ReportRow = components['schemas']['ReportRowOut'];
export type ReportGroup = components['schemas']['ReportGroupOut'];
export type ReportMeasure = components['schemas']['ReportMeasureOut'];
export type ReportEntity = components['schemas']['ReportEntityOut'];
export type ReportField = components['schemas']['ReportFieldOut'];
export type ReportLibrary = components['schemas']['ReportLibraryOut'];
export type BuiltinReport = components['schemas']['BuiltinReportOut'];
export type SavedReport = components['schemas']['SavedReportOut'];
export type ReportFolder = components['schemas']['ReportFolderOut'];
export type ReportInput = components['schemas']['ReportIn'];
export type ReportPatch = components['schemas']['ReportPatch'];
export type ChartType = components['schemas']['ChartType'];
export type DateBucket = components['schemas']['DateBucket'];
export type ResultOrder = components['schemas']['ResultOrder'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Built-in reports you can run, shared folders, saved reports, your stars. */
export function useReportLibrary(enabled = true) {
  return useQuery({
    queryKey: queryKeys.reports.library,
    queryFn: () => call(api.GET('/api/v1/reports/library')),
    enabled,
  });
}

/** What a report on `entity` can use: fields (filter, grouping) and measures. */
export function useReportEntity(entity: string | undefined) {
  return useQuery({
    queryKey: queryKeys.reports.entity(entity ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/reports/entities/{entity}', {
          params: { path: { entity: entity ?? '' } },
        }),
      ),
    enabled: entity !== undefined,
    staleTime: 60_000,
  });
}

/** One saved report (yours, or one in a shared folder). */
export function useSavedReport(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.reports.detail(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/reports/{report_id}', { params: { path: { report_id: id ?? '' } } })),
    enabled: id !== undefined,
    retry: false,
    meta: { silent: true },
  });
}

/**
 * Run a definition over the records you may see. Keeps the last result on screen while a changed
 * definition runs, so adjusting a filter never blanks the chart. Problems (invalid_report,
 * report_timeout) are shown by the viewer itself.
 */
export function useReportRun(definition: ReportDefinition | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.reports.run(definition),
    queryFn: () => {
      if (definition === undefined) throw new Error('report run without a definition');
      return call(api.POST('/api/v1/reports/run', { body: { definition } }));
    },
    enabled: enabled && definition !== undefined,
    placeholderData: keepPreviousData,
    retry: false,
    meta: { silent: true },
  });
}

function useLibraryChanged() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.reports.library });
  };
}

/** Save a report (a copy of a built-in one names it in `copied_from`); one key per save form. */
export function useCreateReport() {
  const changed = useLibraryChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: ReportInput; key: string }) =>
      call(api.POST('/api/v1/reports', { params: { header: { 'Idempotency-Key': key } }, body })),
    onSuccess: changed,
  });
}

/** Change a saved report you may edit (If-Match). */
export function useUpdateReport(id: string) {
  const queryClient = useQueryClient();
  const changed = useLibraryChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: ReportPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/reports/{report_id}', {
          params: { path: { report_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.reports.detail(id), saved);
      changed();
    },
  });
}

export function useDeleteReport(id: string) {
  const queryClient = useQueryClient();
  const changed = useLibraryChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: (version: number) =>
      call(
        api.DELETE('/api/v1/reports/{report_id}', {
          params: { path: { report_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.reports.detail(id) });
      changed();
    },
  });
}

/** Star or unstar a report: `builtin:<code>` or a saved report id. */
export function useStarReport() {
  const changed = useLibraryChanged();
  return useMutation({
    mutationFn: ({ ref, starred }: { ref: string; starred: boolean }) => {
      const params = { path: { report_ref: ref } };
      return starred
        ? call(api.PUT('/api/v1/reports/favourites/{report_ref}', { params }))
        : call(api.DELETE('/api/v1/reports/favourites/{report_ref}', { params }));
    },
    onSuccess: changed,
  });
}

/** Create, rename or delete a shared folder (needs reports.manage_folders). */
export function useReportFolderChange() {
  const changed = useLibraryChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: (
      change:
        | { kind: 'create'; name: string; key: string }
        | { kind: 'rename'; id: string; name: string; version: number }
        | { kind: 'delete'; id: string; version: number; moveTo: string },
    ) => {
      switch (change.kind) {
        case 'create':
          return call(
            api.POST('/api/v1/reports/folders', {
              params: { header: { 'Idempotency-Key': change.key } },
              body: { name: change.name },
            }),
          );
        case 'rename':
          return call(
            api.PATCH('/api/v1/reports/folders/{folder_id}', {
              params: { path: { folder_id: change.id }, header: ifMatch(change.version) },
              body: { name: change.name },
            }),
          );
        case 'delete':
          return call(
            api.DELETE('/api/v1/reports/folders/{folder_id}', {
              params: {
                path: { folder_id: change.id },
                header: ifMatch(change.version),
                query: { move_to: change.moveTo },
              },
            }),
          );
      }
    },
    onSuccess: changed,
  });
}
