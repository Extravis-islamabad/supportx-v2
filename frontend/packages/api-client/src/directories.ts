import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-040 session 2: Admin › Integrations › Directories (integrations.manage_identity). Every
// write is audited server-side; the client secret or certificate goes in and never comes back
// (only its type and ending). The page follows `integrations.directories_changed` on the
// tenant channel and refetches.

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export type Directory = components['schemas']['DirectoryOut'];
export type DirectoryInput = components['schemas']['DirectoryIn'];
export type DirectoryGroup = components['schemas']['DirectoryGroupOut'];

/** Every directory connector with its last run. */
export function useDirectories(enabled = true) {
  return useQuery({
    queryKey: queryKeys.directories.all,
    queryFn: () => call(api.GET('/api/v1/integrations/directories')),
    enabled,
  });
}

function useDirectoriesChanged() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.directories.all });
}

function onConflict(refresh: () => void) {
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) refresh();
  };
}

/** Add a directory; `key` is the Idempotency-Key of this attempt. */
export function useCreateDirectory() {
  const changed = useDirectoriesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: DirectoryInput; key: string }) =>
      call(
        api.POST('/api/v1/integrations/directories', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: changed,
  });
}

/** Replace a directory's settings (leave `credential` out to keep the stored one). */
export function useUpdateDirectory() {
  const changed = useDirectoriesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, body, version }: { id: string; body: DirectoryInput; version: number }) =>
      call(
        api.PUT('/api/v1/integrations/directories/{directory_id}', {
          params: { path: { directory_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: changed,
    onError: onConflict(changed),
  });
}

/** Stop syncing: its people stay and SupportX keeps them. */
export function useRemoveDirectory() {
  const changed = useDirectoriesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/integrations/directories/{directory_id}', {
          params: { path: { directory_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: changed,
    onError: onConflict(changed),
  });
}

/** Run within a minute instead of at the interval. */
export function useSyncDirectoryNow() {
  const changed = useDirectoriesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id }: { id: string }) =>
      call(
        api.POST('/api/v1/integrations/directories/{directory_id}/sync', {
          params: { path: { directory_id: id } },
        }),
      ),
    onSuccess: changed,
  });
}

/** Directory groups whose name starts with `query`, asked with the connector's sync app. */
export function useDirectoryGroups(directoryId: string | null, query: string) {
  return useQuery({
    queryKey: queryKeys.directories.groups(directoryId ?? '', query),
    queryFn: () =>
      call(
        api.GET('/api/v1/integrations/directories/{directory_id}/groups', {
          params: { path: { directory_id: directoryId ?? '' }, query: { q: query } },
        }),
      ),
    enabled: directoryId !== null && query.trim().length > 0,
  });
}
