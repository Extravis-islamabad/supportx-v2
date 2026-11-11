import type { RunAsRoleOut } from '@supportx/api-client';

import { roleName } from '../roleName';

// The steps that change the record act as the workflow's run-as identity (ADR-043 §6); approvals,
// tasks and notices are opened by the workflow itself and need no role of it.
export const ACTING_STEPS = new Set(['set_status', 'field_update', 'note']);

export const named = (t: (key: string) => string, role: RunAsRoleOut) =>
  roleName({ key: role.key, name: role.name, is_system: role.system }, t);

/** Whether the workflow has steps that need its run-as identity to hold a role. */
export function needsRole(nodeTypes: readonly string[]): boolean {
  return nodeTypes.some((type) => ACTING_STEPS.has(type));
}

/**
 * Why the workflow cannot act on records yet, as a label key, or undefined: it has steps that
 * change the record while its run-as identity holds no role (or is not made yet). Shown on the
 * canvas and before publishing; it never blocks (the coordinator, 2026-11-11: an admin chooses
 * the role, nothing is given silently).
 */
export function runAsWarning(
  nodeTypes: readonly string[],
  roles: readonly RunAsRoleOut[] | undefined,
): string | undefined {
  if (!needsRole(nodeTypes) || (roles !== undefined && roles.length > 0)) return undefined;
  return 'workflows.run_as.warning';
}
