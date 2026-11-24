import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Merging duplicate CIs and importing CIs and relationships (WP-053 S4b; REQ-CMDB-017, 018). An
// import's progress arrives on the person's own channel (`cmdb.import_progress`); the CIs it
// changes reach the lists through their own events.

type S = components['schemas'];
export type CiMergePreview = S['CiMergePreviewOut'];
export type CiMergeField = S['CiMergeFieldOut'];
export type CiMergeSide = S['CiMergeSide'];
export type CiMergeResult = S['CiMergeOut'];
export type CiImport = S['CiImportOut'];
export type CiImportKind = S['CiImportKind'];
export type CiImportMode = S['CiImportMode'];
export type CiImportMatch = S['CiImportMatch'];
export type CiImportProblem = S['CiImportProblemOut'];

/** The live message type of an import's progress, on the importer's own channel. */
export const CI_IMPORT_PROGRESS = 'cmdb.import_progress';

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });
const idempotent = (key: string) => ({ 'Idempotency-Key': key });

export const ciMergeKeys = {
  preview: (first: string, second: string) =>
    [...queryKeys.cmdb.all, 'merge-preview', first, second] as const,
  imports: [...queryKeys.cmdb.all, 'imports'] as const,
  import: (id: string) => [...queryKeys.cmdb.all, 'imports', id] as const,
};

/** What merging the two would keep, with the suggested survivor first (cmdb.manage on both). */
export function useCiMergePreview(first: string | undefined, second: string | undefined) {
  return useQuery({
    queryKey: ciMergeKeys.preview(first ?? '', second ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/merges/preview', {
          params: { query: { first: first ?? '', second: second ?? '' } },
        }),
      ),
    enabled: first !== undefined && second !== undefined,
    retry: false,
    meta: { silent: true },
  });
}

/** Merge the duplicate into the survivor, at the versions seen, with the field choices. */
export function useMergeCis() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      key: string;
      survivor: { id: string; version: number };
      merged: { id: string; version: number };
      choices: Record<string, CiMergeSide>;
    }) =>
      call(
        api.POST('/api/v1/cmdb/merges', {
          params: { header: idempotent(input.key) },
          body: {
            survivor_id: input.survivor.id,
            survivor_version: input.survivor.version,
            merged_id: input.merged.id,
            merged_version: input.merged.version,
            choices: input.choices,
          },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.all });
    },
  });
}

/** Your latest CMDB imports. */
export function useCiImports(enabled = true) {
  return useQuery({
    queryKey: ciMergeKeys.imports,
    queryFn: () => call(api.GET('/api/v1/cmdb/imports')),
    enabled,
  });
}

/** One import with its per-row problems. */
export function useCiImport(id: string | undefined) {
  return useQuery({
    queryKey: ciMergeKeys.import(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/cmdb/imports/{import_id}', {
          params: { path: { import_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** Upload a file for a dry run (nothing changes until it is run). */
export function useStartCiImport() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      key: string;
      file: File;
      kind: CiImportKind;
      mode: CiImportMode;
      matchOn: CiImportMatch;
      typeId?: string;
    }) =>
      call(
        api.POST('/api/v1/cmdb/imports', {
          params: {
            header: idempotent(input.key),
            query: {
              name: input.file.name,
              kind: input.kind,
              mode: input.mode,
              match_on: input.matchOn,
              type_id: input.typeId,
              dry_run: true,
            },
          },
          // The raw file is the body (no multipart), like the assets' import.
          body: input.file as unknown as never,
          bodySerializer: (body: unknown) => body as BodyInit,
          headers: { 'Content-Type': 'application/octet-stream' },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(ciMergeKeys.import(job.id), job);
      void queryClient.invalidateQueries({ queryKey: ciMergeKeys.import(job.id) });
      void queryClient.invalidateQueries({ queryKey: ciMergeKeys.imports });
    },
  });
}

/** Run a checked dry run for real (If-Match on the import). */
export function useRunCiImport() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/cmdb/imports/{import_id}/run', {
          params: { header: ifMatch(version), path: { import_id: id } },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(ciMergeKeys.import(job.id), job);
      void queryClient.invalidateQueries({ queryKey: ciMergeKeys.import(job.id) });
    },
  });
}

/** The refused rows as a CSV the server writes in your language, formula-safe (same origin). */
export function ciImportProblemsUrl(id: string, language: 'en' | 'ar' | 'ur'): string {
  return `/api/v1/cmdb/imports/${encodeURIComponent(id)}/problems?language=${language}`;
}
