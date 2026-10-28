import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

export type PermissionInfo = components['schemas']['PermissionOut'];
export type EffectivePermission = components['schemas']['EffectivePermission'];
export type Scope = components['schemas']['GrantIO']['scope'];
export type RoleGrant = components['schemas']['GrantIO'];
export type RoleSummary = components['schemas']['RoleSummary'];
export type RoleDetail = components['schemas']['RoleDetailOut'];
export type RoleInput = components['schemas']['RoleCreate'];
export type UserAccess = components['schemas']['UserAccessOut'];
/** What sites and groups share (the membership screens need no more). */
export type Unit = Pick<
  components['schemas']['SiteOut'],
  'id' | 'name' | 'member_ids' | 'disabled' | 'version'
>;
export type UnitKind = 'sites' | 'groups';

/** GET /permissions: the catalogue (roles.view). */
export function usePermissionCatalogue(enabled = true) {
  return useQuery({
    queryKey: queryKeys.access.catalogue,
    queryFn: () => call(api.GET('/api/v1/permissions')),
    staleTime: 5 * 60_000,
    enabled,
  });
}

/** GET /roles (roles.view). */
export function useRoles(enabled = true) {
  return useQuery({
    queryKey: queryKeys.access.roles,
    queryFn: () => call(api.GET('/api/v1/roles')),
    enabled,
  });
}

/** GET /roles/{id}, with its ETag remembered for the next PATCH/DELETE. */
export function useRole(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.access.role(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/roles/{role_id}', { params: { path: { role_id: id ?? '' } } })),
    enabled: id !== undefined,
  });
}

function useInvalidateAccess() {
  const queryClient = useQueryClient();
  return () => {
    // Roles, assignments and the caller's own permissions may all have changed.
    void queryClient.invalidateQueries({ queryKey: queryKeys.access.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.session });
    void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
  };
}

/** Create, edit and delete custom roles. Errors are shown by the screen (meta.silent). */
export function useRoleMutations() {
  const invalidate = useInvalidateAccess();
  const create = useMutation({
    meta: { silent: true },
    mutationFn: (body: RoleInput) => call(api.POST('/api/v1/roles', { body })),
    onSuccess: invalidate,
  });
  const update = useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: Partial<RoleInput>;
    }) =>
      call(
        api.PATCH('/api/v1/roles/{role_id}', {
          params: { path: { role_id: id }, header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: invalidate,
    // A stale save: fetch the saved role, so the conflict dialog can compare (QA WP-029 BUG-05).
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) invalidate();
    },
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      reassignTo,
    }: {
      id: string;
      version: number;
      reassignTo?: string;
    }) =>
      call(
        api.DELETE('/api/v1/roles/{role_id}', {
          params: {
            path: { role_id: id },
            header: { 'If-Match': `"${String(version)}"` },
            query: { reassign_to: reassignTo },
          },
        }),
      ),
    onSuccess: invalidate,
  });
  return { create, update, remove };
}

/** GET /users/{id}/access: roles, sites and groups of a user (users.view). */
export function useUserAccess(userId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.access.user(userId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/users/{user_id}/access', { params: { path: { user_id: userId ?? '' } } }),
      ),
    enabled: userId !== undefined,
  });
}

/** Assign / remove a role on a user (users.manage). Errors reach the global toast. */
export function useRoleAssignment() {
  const invalidate = useInvalidateAccess();
  const assign = useMutation({
    mutationFn: ({ userId, roleId }: { userId: string; roleId: string }) =>
      call(
        api.PUT('/api/v1/users/{user_id}/roles/{role_id}', {
          params: { path: { user_id: userId, role_id: roleId } },
        }),
      ),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: ({ userId, roleId }: { userId: string; roleId: string }) =>
      call(
        api.DELETE('/api/v1/users/{user_id}/roles/{role_id}', {
          params: { path: { user_id: userId, role_id: roleId } },
        }),
      ),
    onSuccess: invalidate,
  });
  return { assign, remove };
}

/** Sites or support groups with members (sites.view / groups.view). */
export function useUnits(kind: UnitKind, enabled = true) {
  return useQuery({
    queryKey: queryKeys.access.units(kind),
    queryFn: (): Promise<Unit[]> =>
      kind === 'sites'
        ? call(api.GET('/api/v1/organization/sites'))
        : call(api.GET('/api/v1/organization/groups')),
    enabled,
  });
}

/** Create a site/group; add or remove a member (sites.manage / groups.manage). */
export function useUnitMutations(kind: UnitKind) {
  const invalidate = useInvalidateAccess();
  const create = useMutation({
    mutationFn: (name: string): Promise<Unit> =>
      kind === 'sites'
        ? call(api.POST('/api/v1/organization/sites', { body: { name } }))
        : call(api.POST('/api/v1/organization/groups', { body: { name } })),
    onSuccess: invalidate,
  });
  const membership = useMutation({
    mutationFn: ({
      unitId,
      userId,
      member,
    }: {
      unitId: string;
      userId: string;
      member: boolean;
    }) => {
      const params = { params: { path: { unit_id: unitId, user_id: userId } } };
      if (kind === 'sites') {
        return call(
          member
            ? api.PUT('/api/v1/organization/sites/{unit_id}/members/{user_id}', params)
            : api.DELETE('/api/v1/organization/sites/{unit_id}/members/{user_id}', params),
        );
      }
      return call(
        member
          ? api.PUT('/api/v1/organization/groups/{unit_id}/members/{user_id}', params)
          : api.DELETE('/api/v1/organization/groups/{unit_id}/members/{user_id}', params),
      );
    },
    onSuccess: invalidate,
  });
  return { create, membership };
}
