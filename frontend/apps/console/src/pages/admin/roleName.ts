import type { PermissionInfo, RoleSummary } from '@supportx/api-client';

/** System roles render through labels (`role.<key>`); custom role names are the admin's own text. */
export function roleName(
  role: Pick<RoleSummary, 'key' | 'name' | 'is_system'>,
  t: (key: string) => string,
): string {
  return role.is_system ? t(`role.${role.key}`) : role.name;
}

/** The permission catalogue grouped by module, in catalogue order (the editor's and compare's rows). */
export function groupByModule(catalogue: PermissionInfo[]): [string, PermissionInfo[]][] {
  const groups = new Map<string, PermissionInfo[]>();
  for (const permission of catalogue) {
    groups.set(permission.module, [...(groups.get(permission.module) ?? []), permission]);
  }
  return [...groups.entries()];
}
