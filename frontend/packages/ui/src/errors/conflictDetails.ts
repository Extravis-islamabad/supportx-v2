import { ApiError } from '@supportx/api-client';

/** Who changed a record, when, and which fields: from the 409, or by comparing versions. */
export interface Explanation {
  by: string;
  at: string | null;
  fields: string[];
}

// Bookkeeping, not something a person changed.
const NOT_FIELDS = new Set([
  'id',
  'version',
  'created_at',
  'created_by',
  'updated_at',
  'updated_by',
  'people',
  'operations',
]);

/** Top-level fields whose values differ between two versions of a record. */
export function changedFields(opened: object, latest: object): string[] {
  const before = opened as Record<string, unknown>;
  const after = latest as Record<string, unknown>;
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
    (key) => !NOT_FIELDS.has(key) && JSON.stringify(before[key]) !== JSON.stringify(after[key]),
  );
}

export function explain(error: unknown, opened?: object, latest?: object): Explanation | null {
  if (!(error instanceof ApiError) || !error.isConflict) return null;
  const { changed_by: by, changed_at: at, changed_fields: fields } = error.params;
  const listed = typeof fields === 'string' && fields !== '' ? fields.split(',') : [];
  const found = {
    by: typeof by === 'string' ? by : '',
    at: typeof at === 'string' ? at : null,
    fields:
      listed.length > 0 || opened === undefined || latest === undefined
        ? listed
        : changedFields(opened, latest),
  };
  return found.by === '' && found.fields.length === 0 ? null : found;
}
