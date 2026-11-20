import type { IncidentListField } from '@supportx/api-client';

import type { ColumnSpec } from './columns';

/** What a card shows below its ID and subject, in this order (REQ-INC-111). */
export const CARD_FIELDS = ['status', 'priority', 'technician_id', 'resolution_due_at'] as const;

/**
 * Only the fields the server lists for this reader: a field their role hides or masks (ADR-047)
 * is not in the list's fields, so it never reaches a card (lane C's condition 3).
 */
export function cardSpecs(
  specs: Map<string, ColumnSpec>,
  fields: readonly IncidentListField[],
): ColumnSpec[] {
  const listed = new Set(fields.map((f) => f.name));
  return CARD_FIELDS.filter((key) => listed.has(key))
    .map((key) => specs.get(key))
    .filter((s): s is ColumnSpec => s !== undefined);
}
