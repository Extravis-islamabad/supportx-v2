import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { listSettingKey, type SharedListKind } from './incidentLists';
import type { components } from './schema';

// The shared list-settings store (WP-049b s4a; `/list-settings/{list_key}`): your saved views
// and favourites of a list. Widths and columns of one view go through useListSetting /
// useSaveListSetting with the list as `kind`, which share this store.

export type SharedViewSetting = components['schemas']['ViewSettingOut'];
export type SharedListSettings = components['schemas']['ListSettingsOut'];
export type SharedSavedViewInput = components['schemas']['SavedListViewIn'];
export type SharedSavedViewPatch = components['schemas']['SavedListViewPatch'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export const sharedListKeys = {
  all: (list: SharedListKind) => [list, 'list-settings'] as const,
  mine: (list: SharedListKind) => [list, 'list-settings', 'mine'] as const,
};

/** Everything you keep for a list: your saved views by name, then built-in views' settings. */
export function useSharedListSettings(list: SharedListKind, enabled = true) {
  return useQuery({
    queryKey: sharedListKeys.mine(list),
    queryFn: () =>
      call(api.GET('/api/v1/list-settings/{list_key}', { params: { path: { list_key: list } } })),
    enabled,
  });
}

export type SharedSavedViewChange =
  | { kind: 'create'; key: string; view: SharedSavedViewInput }
  | { kind: 'update'; id: string; version: number; view: SharedSavedViewPatch }
  | { kind: 'delete'; id: string; version: number };

/** Save, change or remove one of your views of the list. */
export function useSharedSavedViewChange(list: SharedListKind) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (change: SharedSavedViewChange): Promise<SharedViewSetting | null> => {
      if (change.kind === 'create') {
        return call(
          api.POST('/api/v1/list-settings/{list_key}/saved-views', {
            params: { path: { list_key: list }, header: { 'Idempotency-Key': change.key } },
            body: change.view,
          }),
        );
      }
      const path = { list_key: list, view_id: change.id };
      if (change.kind === 'update') {
        return call(
          api.PATCH('/api/v1/list-settings/{list_key}/saved-views/{view_id}', {
            params: { path, header: ifMatch(change.version) },
            body: change.view,
          }),
        );
      }
      await call(
        api.DELETE('/api/v1/list-settings/{list_key}/saved-views/{view_id}', {
          params: { path, header: ifMatch(change.version) },
        }),
      );
      return null;
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: sharedListKeys.all(list) });
    },
  });
}

/**
 * Star a view or not (REQ-INC-107: favourites first in the view picker). Your own setting, so a
 * 409 from another window of yours is settled by reading the version and starring once more.
 */
export function useFavouriteView(list: SharedListKind) {
  const queryClient = useQueryClient();
  const put = (viewKey: string, current: SharedViewSetting, favourite: boolean) =>
    call(
      api.PUT('/api/v1/list-settings/{list_key}/views/{view_key}', {
        params: {
          path: { list_key: list, view_key: viewKey },
          header: current.version == null ? {} : ifMatch(current.version),
        },
        body: {
          columns: current.columns,
          sort: current.sort,
          page_size: current.page_size,
          favourite,
        },
      }),
    );
  const read = (viewKey: string) =>
    call(
      api.GET('/api/v1/list-settings/{list_key}/views/{view_key}', {
        params: { path: { list_key: list, view_key: viewKey } },
      }),
    );
  return useMutation({
    mutationFn: async ({ viewKey, favourite }: { viewKey: string; favourite: boolean }) => {
      const current = await read(viewKey);
      try {
        return await put(viewKey, current, favourite);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        return put(viewKey, await read(viewKey), favourite);
      }
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(listSettingKey(list, saved.view_key), saved);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: sharedListKeys.all(list) });
    },
  });
}
