import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// Dashboards (WP-036). Widgets are report definitions: the console runs each through the
// report engine (`useReportRun`), so a widget counts exactly what the viewer could list.
export type Dashboard = components['schemas']['DashboardOut'];
export type DashboardList = components['schemas']['DashboardListOut'];
export type DashboardBody = components['schemas']['DashboardBody-Input'];
export type DashboardWidget = components['schemas']['Widget-Input'];
export type DashboardFilters = components['schemas']['DashboardFilters'];
export type DashboardInput = components['schemas']['DashboardIn'];
export type DashboardPatch = components['schemas']['DashboardPatch'];
export type DashboardHome = components['schemas']['HomeOut'];

/** In a widget filter value: the viewer (replace with their id before running). */
export const DASHBOARD_ME = '@me';

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Every dashboard you may see (built-in, shared, yours), your favourites and your home. */
export function useDashboards(enabled = true) {
  return useQuery({
    queryKey: queryKeys.dashboards.list,
    queryFn: () => call(api.GET('/api/v1/dashboards')),
    enabled,
  });
}

/** One dashboard; a 404 (deleted, or no longer shared with you) is shown by the screen. */
export function useDashboard(ref: string | undefined) {
  return useQuery({
    queryKey: queryKeys.dashboards.detail(ref ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/dashboards/{ref}', { params: { path: { ref: ref ?? '' } } })),
    enabled: ref !== undefined,
    retry: false,
    meta: { silent: true },
  });
}

function useListChanged() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.dashboards.all });
  };
}

/** Create or copy a dashboard (a copy names its original in `copied_from`). */
export function useCreateDashboard() {
  const changed = useListChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: DashboardInput; key: string }) =>
      call(
        api.POST('/api/v1/dashboards', { params: { header: { 'Idempotency-Key': key } }, body }),
      ),
    onSuccess: changed,
  });
}

/** Change a dashboard you may edit (If-Match): name, sharing, widgets and layout. */
export function useUpdateDashboard(ref: string) {
  const queryClient = useQueryClient();
  const changed = useListChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: DashboardPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/dashboards/{ref}', {
          params: { path: { ref }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.dashboards.detail(ref), saved);
      changed();
    },
  });
}

/** Delete a dashboard you may edit (If-Match). */
export function useDeleteDashboard(ref: string) {
  const changed = useListChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: (version: number) =>
      call(
        api.DELETE('/api/v1/dashboards/{ref}', {
          params: { path: { ref }, header: ifMatch(version) },
        }),
      ),
    onSuccess: changed,
  });
}

/** Choose your home dashboard (null: back to your role's). */
export function useSetHome() {
  const changed = useListChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: (ref: string | null) =>
      call(api.PUT('/api/v1/dashboards/home', { body: { dashboard_ref: ref } })),
    onSuccess: changed,
  });
}

/** Star or unstar a dashboard (favourites first in the picker). */
export function useStarDashboard() {
  const changed = useListChanged();
  return useMutation({
    mutationFn: ({ ref, starred }: { ref: string; starred: boolean }) =>
      starred
        ? call(api.PUT('/api/v1/dashboards/favourites/{ref}', { params: { path: { ref } } }))
        : call(api.DELETE('/api/v1/dashboards/favourites/{ref}', { params: { path: { ref } } })),
    onSuccess: changed,
  });
}

/** Home dashboards admins set per role (needs `dashboards.manage_defaults`). */
export function useRoleHomes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.dashboards.roleHomes,
    queryFn: () => call(api.GET('/api/v1/dashboards/role-homes')),
    enabled,
  });
}

/** Set (or clear, null) a role's home dashboard. */
export function useSetRoleHome() {
  const changed = useListChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ roleKey, ref }: { roleKey: string; ref: string | null }) =>
      call(
        api.PUT('/api/v1/dashboards/role-homes/{role_key}', {
          params: { path: { role_key: roleKey } },
          body: { dashboard_ref: ref },
        }),
      ),
    onSuccess: changed,
  });
}
