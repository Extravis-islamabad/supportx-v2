import type { BoardGroupBy, FilterExpression } from '@supportx/api-client';

/** Columns shown at once when they are people or groups; the rest are under "More columns". */
export const BOARD_COLUMNS_SHOWN = 12;

const FIELD: Record<BoardGroupBy, string> = {
  status: 'status',
  priority: 'priority',
  technician: 'technician_id',
  group: 'group_id',
};

export const both = (a: FilterExpression | undefined, b: FilterExpression): FilterExpression =>
  a === undefined ? b : { and: [a, b] };

/** The column's own condition, added to the view's filter: the list's query, narrowed. */
export function columnCondition(groupBy: BoardGroupBy, key: string | null): FilterExpression {
  return (
    key === null
      ? { field: FIELD[groupBy], op: 'is_null' }
      : { field: FIELD[groupBy], op: 'eq', value: key }
  ) as FilterExpression;
}
