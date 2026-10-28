import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call, rememberEtag } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';
import type { UserDetail } from './users';

export type PersonIn = components['schemas']['PersonIn'];
export type PersonFields = components['schemas']['PersonFields'];
export type PeopleImport = components['schemas']['ImportOut'];
export type ImportProblem = components['schemas']['ImportProblem'];
export type AccessSettings = components['schemas']['AccessSettingsOut'];
export type TechnicianScope = AccessSettings['technician_scope'];
export type Reactivation = components['schemas']['ReactivationOut'];

function ifMatch(version: number) {
  return { 'If-Match': `"${String(version)}"` };
}

/** After any person change: the record, every users list and the access screens. */
function useSettle() {
  const queryClient = useQueryClient();
  return (user: UserDetail) => {
    rememberEtag(`/api/v1/users/${user.id}`, `"${String(user.version)}"`);
    queryClient.setQueryData(queryKeys.users.detail(user.id), user);
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.users.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.access.all });
  };
}

/**
 * People administration (WP-021): add, edit the record, technician or requester, sign-in,
 * deactivate and reactivate. Each change sends the version the editor started from (If-Match);
 * errors are shown by the editor (fields, conflict dialog, seat limit), so no global toast.
 */
export function usePersonChange() {
  const settle = useSettle();
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (body: PersonIn) => call(api.POST('/api/v1/users', { body })),
    onSuccess: settle,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, body }: { id: string; version: number; body: PersonFields }) =>
      call(
        api.PATCH('/api/v1/users/{user_id}/person', {
          params: { path: { user_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: settle,
  });
  const setType = useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      userType,
    }: {
      id: string;
      version: number;
      userType: UserDetail['user_type'];
    }) =>
      call(
        api.PUT('/api/v1/users/{user_id}/type', {
          params: { path: { user_id: id }, header: ifMatch(version) },
          body: { user_type: userType },
        }),
      ),
    onSuccess: settle,
  });
  const setSignIn = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, allowed }: { id: string; version: number; allowed: boolean }) =>
      call(
        api.PUT('/api/v1/users/{user_id}/sign-in', {
          params: { path: { user_id: id }, header: ifMatch(version) },
          body: { allowed },
        }),
      ),
    onSuccess: settle,
  });
  const deactivate = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/users/{user_id}/deactivate', {
          params: { path: { user_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: settle,
  });
  const reactivate = useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      keepRoleIds,
      keepGroupIds,
    }: {
      id: string;
      version: number;
      keepRoleIds: string[];
      keepGroupIds: string[];
    }) =>
      call(
        api.POST('/api/v1/users/{user_id}/reactivate', {
          params: { path: { user_id: id }, header: ifMatch(version) },
          body: { keep_role_ids: keepRoleIds, keep_group_ids: keepGroupIds },
        }),
      ),
    onSuccess: settle,
  });
  return { create, update, setType, setSignIn, deactivate, reactivate };
}

/** What a deactivated person still holds (roles, groups), offered before reactivating. */
export function useReactivation(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.people.reactivation(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/users/{user_id}/reactivation', {
          params: { path: { user_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
    staleTime: 0,
  });
}

/** The latest people imports (users.manage); progress arrives live (`people_imports`). */
export function usePeopleImports(enabled = true) {
  return useQuery({
    queryKey: queryKeys.people.imports,
    queryFn: () => call(api.GET('/api/v1/people-imports')),
    enabled,
  });
}

/** Upload a CSV or Excel file; it is imported in the background. */
export function useStartPeopleImport() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ file, matchOn }: { file: File; matchOn: 'email' | 'employee_id' }) =>
      call(
        api.POST('/api/v1/people-imports', {
          params: { query: { name: file.name, match_on: matchOn } },
          // The raw file is the body (no multipart), like file uploads (WP-022).
          body: file as unknown as never,
          bodySerializer: (body: unknown) => body as BodyInit,
          headers: { 'Content-Type': 'application/octet-stream' },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.people.imports });
    },
  });
}

/** What the built-in technician role sees (D-073); `answered_at` null: not asked yet. */
export function useAccessSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.people.accessSettings,
    queryFn: () => call(api.GET('/api/v1/access-settings')),
    // The first-run question and the settings card simply stay hidden if this fails.
    meta: { silent: true },
    enabled,
  });
}

/** Answer (or change) the technician-visibility question. */
export function useSaveAccessSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ scope, version }: { scope: TechnicianScope; version: number }) =>
      call(
        api.PUT('/api/v1/access-settings', {
          params: { header: ifMatch(version) },
          body: { technician_scope: scope },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.people.accessSettings, saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.access.all });
    },
    onError: (error) => {
      // A stale save: fetch the saved answer, so the conflict dialog can compare (QA WP-029 BUG-05).
      if (error instanceof ApiError && error.isConflict) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.people.accessSettings });
      }
    },
  });
}
