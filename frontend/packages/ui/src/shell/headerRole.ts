// Most senior first: the header names the role that best says what the person may do (QA6-SH-01:
// it showed the user type, so a tenant admin read "Technician").
const HEADER_ROLES = [
  'tenant_admin',
  'security_admin',
  'service_desk_manager',
  'site_admin',
  'knowledge_manager',
  'problem_manager',
  'auditor',
  'report_viewer',
  'technician',
  'requester',
] as const;

/** The signed-in person's role for the top bar, else their user type (custom roles only). */
export function headerRole(
  t: (key: string) => string,
  user: { roles?: readonly string[]; user_type: string },
): string {
  const held = new Set(user.roles ?? []);
  const role = HEADER_ROLES.find((key) => held.has(key));
  return role === undefined ? t(`user_type.${user.user_type}`) : t(`role.${role}`);
}
