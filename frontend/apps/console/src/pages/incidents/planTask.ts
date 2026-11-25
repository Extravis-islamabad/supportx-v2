import type { IncidentTask } from '@supportx/api-client';

/** Whether a plan task has parts of its own to show (WP-047a S5). */
export function hasPlanParts(task: IncidentTask): boolean {
  return (task.fields ?? []).length > 0 || task.kind === 'asset_handover' || task.needs_review;
}
