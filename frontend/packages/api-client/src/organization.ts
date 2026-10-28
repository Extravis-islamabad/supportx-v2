import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

export type SiteOut = components['schemas']['SiteOut'];
export type SiteIn = components['schemas']['SiteIn'];
export type SitePatch = components['schemas']['SitePatch'];
export type GroupOut = components['schemas']['GroupOut'];
export type GroupIn = components['schemas']['GroupIn'];
export type GroupPatch = components['schemas']['GroupPatch'];
export type DepartmentOut = components['schemas']['DepartmentOut'];
export type DepartmentIn = components['schemas']['DepartmentIn'];
export type DepartmentPatch = components['schemas']['DepartmentPatch'];
export type DeskOut = components['schemas']['DeskOut'];
export type DeskIn = components['schemas']['DeskIn'];
export type DeskPatch = components['schemas']['DeskPatch'];

/** The organisation's structure (WP-021): sites, support groups, departments, desks (ESM). */
export type StructureKind = 'sites' | 'groups' | 'departments' | 'desks';

interface Rows {
  sites: SiteOut;
  groups: GroupOut;
  departments: DepartmentOut;
  desks: DeskOut;
}
interface Creates {
  sites: SiteIn;
  groups: GroupIn;
  departments: DepartmentIn;
  desks: DeskIn;
}
interface Patches {
  sites: SitePatch;
  groups: GroupPatch;
  departments: DepartmentPatch;
  desks: DeskPatch;
}

function list(kind: StructureKind) {
  switch (kind) {
    case 'sites':
      return call(api.GET('/api/v1/organization/sites'));
    case 'groups':
      return call(api.GET('/api/v1/organization/groups'));
    case 'departments':
      return call(api.GET('/api/v1/organization/departments'));
    case 'desks':
      return call(api.GET('/api/v1/organization/desks'));
  }
}

/** Every site / group / department / desk, inactive ones included (marked `disabled`). */
export function useStructure<K extends StructureKind>(kind: K, enabled = true, silent = false) {
  return useQuery({
    // `silent`: a screen where the list only feeds optional filters reports nothing itself.
    meta: { silent },
    // Sites and groups share the WP-016 keys, so the membership screens refresh too.
    queryKey:
      kind === 'sites' || kind === 'groups'
        ? queryKeys.access.units(kind)
        : queryKeys.organization.list(kind),
    queryFn: async () => (await list(kind)) as Rows[K][],
    enabled,
  });
}

function ifMatch(version: number) {
  return { 'If-Match': `"${String(version)}"` };
}

/**
 * Add, change and remove one kind of unit. Changes carry the version the editor started from
 * (If-Match), so a save made elsewhere meanwhile answers 409 instead of being overwritten.
 * Errors are shown by the editor itself (fields, conflict dialog, "in use" counts).
 */
export function useStructureChange<K extends StructureKind>(kind: K) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.access.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.organization.all });
  };
  const create = useMutation({
    meta: { silent: true },
    mutationFn: async (body: Creates[K]) => {
      switch (kind) {
        case 'sites':
          return call(api.POST('/api/v1/organization/sites', { body: body as SiteIn }));
        case 'groups':
          return call(api.POST('/api/v1/organization/groups', { body: body as GroupIn }));
        case 'departments':
          return call(api.POST('/api/v1/organization/departments', { body: body as DepartmentIn }));
        default:
          return call(api.POST('/api/v1/organization/desks', { body: body as DeskIn }));
      }
    },
    onSuccess: refresh,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: async ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: Patches[K];
    }) => {
      const header = ifMatch(version);
      switch (kind) {
        case 'sites':
          return call(
            api.PATCH('/api/v1/organization/sites/{unit_id}', {
              params: { path: { unit_id: id }, header },
              body: body,
            }),
          );
        case 'groups':
          return call(
            api.PATCH('/api/v1/organization/groups/{unit_id}', {
              params: { path: { unit_id: id }, header },
              body: body,
            }),
          );
        case 'departments':
          return call(
            api.PATCH('/api/v1/organization/departments/{department_id}', {
              params: { path: { department_id: id }, header },
              body: body,
            }),
          );
        default:
          return call(
            api.PATCH('/api/v1/organization/desks/{desk_id}', {
              params: { path: { desk_id: id }, header },
              body: body,
            }),
          );
      }
    },
    onSuccess: refresh,
    // A stale change: fetch the saved unit, so the conflict dialog can compare (BUG-05).
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: async ({ id, version }: { id: string; version: number }) => {
      const header = ifMatch(version);
      switch (kind) {
        case 'sites':
          return call(
            api.DELETE('/api/v1/organization/sites/{unit_id}', {
              params: { path: { unit_id: id }, header },
            }),
          );
        case 'groups':
          return call(
            api.DELETE('/api/v1/organization/groups/{unit_id}', {
              params: { path: { unit_id: id }, header },
            }),
          );
        default:
          return call(
            api.DELETE('/api/v1/organization/departments/{department_id}', {
              params: { path: { department_id: id }, header },
            }),
          );
      }
    },
    onSuccess: refresh,
    // A stale change: fetch the saved unit, so the conflict dialog can compare (BUG-05).
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) refresh();
    },
  });
  return { create, update, remove };
}
