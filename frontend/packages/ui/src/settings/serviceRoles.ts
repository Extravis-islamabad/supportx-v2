import type { ServiceRoleOut } from '@supportx/api-client';

/** A role's name: system roles through labels (`role.<key>`), custom ones as the admin wrote. */
export function serviceRoleName(t: (key: string) => string, role: ServiceRoleOut): string {
  return role.system ? t(`role.${role.key}`) : role.name;
}
