import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';
import type { FilterExpression } from './users';

export type AuditEntry = components['schemas']['AuditEntryOut'];
export type AuditEntryDetail = components['schemas']['AuditEntryDetailOut'];
export type AuditEntryPage = components['schemas']['AuditEntryPage'];
export type AuditStatus = components['schemas']['AuditStatusOut'];
export type AuditRun = components['schemas']['AuditRunOut'];
export type AuditSettings = components['schemas']['AuditSettingsOut'];
export type AuditSettingsInput = components['schemas']['AuditSettingsIn'];
export type AuditExport = components['schemas']['AuditExportOut'];
export type AuditExportInput = components['schemas']['AuditExportIn'];
export type AuditSavedSearch = components['schemas']['AuditSavedSearchOut'];
export type AuditCategory = components['schemas']['AuditCategory'];
export type AuditOutcome = components['schemas']['AuditOutcome'];
export type AuditActorType = components['schemas']['AuditActorType'];
export type AuditClient = components['schemas']['AuditClient'];
export type AuditReadCategory = components['schemas']['ReadCategory'];

/** List parameters the audit screen controls: simple filters plus a time-range expression. */
export interface AuditEntriesQuery {
  /** Simple equality filters (actor_id, action, category, outcome, client, object_type ...). */
  params?: Record<string, string>;
  filter?: FilterExpression;
  sort?: string;
}

/** GET /audit/entries, newest first, with cursor pagination (reading it is itself audited). */
export function useAuditEntries(query: AuditEntriesQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.audit.list(query),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/audit/entries', {
          params: {
            query: {
              ...query.params,
              filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
              sort: query.sort,
              limit: 50,
              cursor: pageParam ?? undefined,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

/** One entry with its chain position, hashes and personal values. */
export function useAuditEntry(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.audit.entry(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/audit/entries/{entry_id}', { params: { path: { entry_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** Sealing, anchoring, latest verifications and the unresolved alert (banner). */
export function useAuditStatus(enabled = true) {
  return useQuery({
    // A background check for the banner: a failure here is not the user's problem to see.
    meta: { silent: true },
    queryKey: queryKeys.audit.status,
    queryFn: () => call(api.GET('/api/v1/audit/status')),
    enabled,
  });
}

/** The latest verification runs. */
export function useAuditRuns(enabled = true) {
  return useQuery({
    queryKey: queryKeys.audit.runs,
    queryFn: () => call(api.GET('/api/v1/audit/verification-runs')),
    enabled,
  });
}

/** Ask for a verification of a range now (runs in the background). */
export function useStartAuditRun() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (body: { range_from?: string | null; range_to?: string | null }) =>
      call(api.POST('/api/v1/audit/verification-runs', { body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.audit.runs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.audit.status });
    },
  });
}

/** Audit settings (defaults until changed); the ETag is kept for the next PUT. */
export function useAuditSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.audit.settings,
    queryFn: () => call(api.GET('/api/v1/audit/settings')),
    enabled,
  });
}

/** PUT /audit/settings with If-Match for the version that was read. */
export function useUpdateAuditSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: AuditSettingsInput; version: number }) =>
      call(
        api.PUT('/api/v1/audit/settings', {
          params: { header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.audit.settings, saved);
    },
  });
}

/** The latest exports. */
export function useAuditExports(enabled = true) {
  return useQuery({
    queryKey: queryKeys.audit.exports,
    queryFn: () => call(api.GET('/api/v1/audit/exports')),
    enabled,
  });
}

/** Ask for an export (built in the background). */
export function useStartAuditExport() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (body: AuditExportInput) => call(api.POST('/api/v1/audit/exports', { body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.audit.exports });
    },
  });
}

/** Download a ready export as a file (the download is audited). */
export async function downloadAuditExport(id: string): Promise<Blob> {
  return call(
    api.GET('/api/v1/audit/exports/{export_id}/download', {
      params: { path: { export_id: id } },
      parseAs: 'blob',
    }),
  );
}

/** Your saved searches. */
export function useAuditSavedSearches(enabled = true) {
  return useQuery({
    queryKey: queryKeys.audit.saved,
    queryFn: () => call(api.GET('/api/v1/audit/saved-searches')),
    enabled,
  });
}

/** Save or delete one of your searches. */
export function useAuditSavedSearchMutations() {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.audit.saved });
  };
  const save = useMutation({
    meta: { silent: true },
    mutationFn: (body: { name: string; query: Record<string, string> }) =>
      call(api.POST('/api/v1/audit/saved-searches', { body })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      call(
        api.DELETE('/api/v1/audit/saved-searches/{search_id}', {
          params: { path: { search_id: id } },
        }),
      ),
    onSuccess: refresh,
  });
  return { save, remove };
}
