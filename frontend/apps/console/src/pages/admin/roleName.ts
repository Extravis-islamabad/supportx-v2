import type { RoleSummary } from '@supportx/api-client';

/** System roles render through labels (`role.<key>`); custom role names are the admin's own text. */
export function roleName(
  role: Pick<RoleSummary, 'key' | 'name' | 'is_system'>,
  t: (key: string) => string,
): string {
  return role.is_system ? t(`role.${role.key}`) : role.name;
}
