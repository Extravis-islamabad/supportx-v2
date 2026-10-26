import { useMemo } from 'react';

import { useSession, type EffectivePermission } from '@supportx/api-client';

/** Permissions that make the console's Admin area visible (any one of them; WP-016). */
export const ADMIN_PERMISSIONS = [
  'users.manage',
  'roles.view',
  'roles.manage',
  'sites.manage',
  'groups.manage',
  'settings.manage',
  'files.manage',
  'licence.manage',
  'audit.view',
] as const;

export interface Access {
  /** Whether the user holds the permission at any scope. */
  can: (permission: string) => boolean;
  /** Whether the user holds any of the permissions. */
  canAny: (permissions: readonly string[]) => boolean;
  permission: (key: string) => EffectivePermission | undefined;
}

/**
 * What the signed-in user may do, from GET /auth/me (WP-016). Only for showing and hiding UI:
 * the server checks every request again.
 */
export function useAccess(): Access {
  const permissions = useSession().data?.permissions;
  return useMemo(() => {
    const byKey = new Map((permissions ?? []).map((p) => [p.key, p]));
    return {
      can: (key) => byKey.has(key),
      canAny: (keys) => keys.some((key) => byKey.has(key)),
      permission: (key) => byKey.get(key),
    };
  }, [permissions]);
}
