import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Bulk jobs, merges and imports on the asset list (WP-049b S4b; REQ-AST-051, 052, 053). A bulk
// job's and an import's progress arrive on the person's own channel (`assets.bulk_progress`,
// `assets.import_progress`); the assets they change reach the lists through their own events.

type S = components['schemas'];
export type AssetBulkAction = S['AssetBulkAction'];
export type AssetBulkChanges = S['AssetBulkChanges'];
export type AssetBulkJob = S['AssetBulkJobOut'];
export type AssetBulkResult = S['AssetBulkResultOut'];
export type AssetMergePreview = S['AssetMergePreviewOut'];
export type AssetMergeField = S['AssetMergeFieldOut'];
export type AssetMergeSide = S['MergeSide'];
export type AssetMergeResult = S['AssetMergeOut'];
export type AssetImport = S['AssetImportOut'];
export type AssetImportKind = S['ImportKind'];
export type AssetImportMode = S['ImportMode'];
export type AssetImportMatch = S['ImportMatch'];
export type AssetImportProblem = S['AssetImportProblemOut'];

/** The cap of one bulk job (architecture.md §10); the server says so too (422). */
export const ASSET_BULK_MAX = 1000;
/** The live message types of this file's jobs. */
export const ASSET_BULK_PROGRESS = 'assets.bulk_progress';
export const ASSET_IMPORT_PROGRESS = 'assets.import_progress';

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });
const idempotent = (key: string) => ({ 'Idempotency-Key': key });

export const assetBatchKeys = {
  bulkJob: (id: string) => [...queryKeys.assets.all, 'bulk-job', id] as const,
  mergePreview: (first: string, second: string) =>
    [...queryKeys.assets.all, 'merge-preview', first, second] as const,
  imports: [...queryKeys.assets.all, 'imports'] as const,
  import: (id: string) => [...queryKeys.assets.all, 'imports', id] as const,
};

// --- bulk jobs -------------------------------------------------------------------------------

/** Queue a bulk job on the picked assets; each is checked on the server as it runs. */
export function useStartAssetBulk() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      key,
      action,
      assetIds,
      changes,
    }: {
      key: string;
      action: AssetBulkAction;
      assetIds: string[];
      changes: AssetBulkChanges;
    }) =>
      call(
        api.POST('/api/v1/assets/bulk-jobs', {
          params: { header: idempotent(key) },
          body: { action, asset_ids: assetIds, changes },
        }),
      ),
    onSuccess: (job) => {
      // Shown at once, then read again: a fast job may have moved on before the screen listens.
      queryClient.setQueryData(assetBatchKeys.bulkJob(job.id), job);
      void queryClient.invalidateQueries({ queryKey: assetBatchKeys.bulkJob(job.id) });
    },
  });
}

/** One of your bulk jobs with its per-asset results (refetched on its progress message). */
export function useAssetBulkJob(id: string | undefined) {
  return useQuery({
    queryKey: assetBatchKeys.bulkJob(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/bulk-jobs/{job_id}', { params: { path: { job_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

// --- merges ----------------------------------------------------------------------------------

/** What merging the two would keep, with the suggested survivor first. */
export function useAssetMergePreview(first: string | undefined, second: string | undefined) {
  return useQuery({
    queryKey: assetBatchKeys.mergePreview(first ?? '', second ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/merge-preview', {
          params: { query: { first: first ?? '', second: second ?? '' } },
        }),
      ),
    enabled: first !== undefined && second !== undefined,
    retry: false,
    meta: { silent: true },
  });
}

/** Merge the duplicate into the survivor, at the versions seen, with the field choices. */
export function useMergeAssets() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      key: string;
      survivor: { id: string; version: number };
      merged: { id: string; version: number };
      choices: Record<string, AssetMergeSide>;
    }) =>
      call(
        api.POST('/api/v1/assets/merges', {
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
    },
  });
}

/** Restore from the trash; `confirmMerged` after the merged-asset warning (REQ-AST-052). */
export function useRestoreAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, confirmMerged }: { id: string; confirmMerged: boolean }) =>
      call(
        api.POST('/api/v1/assets/{asset_id}/restore', {
          params: { path: { asset_id: id }, query: { confirm_merged: confirmMerged } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
    },
  });
}

// --- imports ---------------------------------------------------------------------------------

/** Your latest imports. */
export function useAssetImports(enabled = true) {
  return useQuery({
    queryKey: assetBatchKeys.imports,
    queryFn: () => call(api.GET('/api/v1/assets/imports')),
    enabled,
  });
}

/** One import with its per-row problems. */
export function useAssetImport(id: string | undefined) {
  return useQuery({
    queryKey: assetBatchKeys.import(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/assets/imports/{import_id}', {
          params: { path: { import_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** Upload a file for a dry run (nothing changes until it is run). */
export function useStartAssetImport() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (input: {
      key: string;
      file: File;
      kind: AssetImportKind;
      mode: AssetImportMode;
      matchOn: AssetImportMatch;
    }) =>
      call(
        api.POST('/api/v1/assets/imports', {
          params: {
            header: idempotent(input.key),
            query: {
              name: input.file.name,
              kind: input.kind,
              mode: input.mode,
              match_on: input.matchOn,
              dry_run: true,
            },
          },
          // The raw file is the body (no multipart), like the people import.
          body: input.file as unknown as never,
          bodySerializer: (body: unknown) => body as BodyInit,
          headers: { 'Content-Type': 'application/octet-stream' },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(assetBatchKeys.import(job.id), job);
      void queryClient.invalidateQueries({ queryKey: assetBatchKeys.import(job.id) });
      void queryClient.invalidateQueries({ queryKey: assetBatchKeys.imports });
    },
  });
}

/** Run a checked dry run for real (If-Match on the import). */
export function useRunAssetImport() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/assets/imports/{import_id}/run', {
          params: { header: ifMatch(version), path: { import_id: id } },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData(assetBatchKeys.import(job.id), job);
      void queryClient.invalidateQueries({ queryKey: assetBatchKeys.import(job.id) });
    },
  });
}
