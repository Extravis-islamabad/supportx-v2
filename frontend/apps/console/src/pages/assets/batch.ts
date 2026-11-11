import type {
  AssetBulkAction,
  AssetBulkChanges,
  AssetImport,
  AssetImportProblem,
} from '@supportx/api-client';
import { en } from '@supportx/labels';
import type { useLabel } from '@supportx/ui';

// The words and shapes of the asset list's bulk jobs, imports and export (WP-049b S4b): plain
// functions, kept apart from the components so each can be tested on its own.

type T = ReturnType<typeof useLabel>;

/** A skip's reason in words: the field's message where there is one, else the problem's. */
export function reasonText(
  t: T,
  code: string | null | undefined,
  field: string | null | undefined,
  params: Record<string, unknown> = {},
): string {
  if (code == null) return '';
  const fieldKey = `errors.field.${code}`;
  const plainKey = `errors.${code}`;
  const known = (key: string) => key in en;
  const given = params as Record<string, string | number>;
  if (field != null && field !== 'row' && known(fieldKey)) return t(fieldKey, given);
  if (known(plainKey)) return t(plainKey, given);
  if (known(fieldKey)) return t(fieldKey, given);
  return t('errors.internal_error');
}

/** What the person filled in, as the job's changes (only what they set). */
export function bulkChanges(
  action: AssetBulkAction,
  form: {
    location: string;
    costCentre: string;
    glCode: string;
    siteId?: string;
    stateId?: string;
    reason: string;
    holderKind: 'none' | 'user' | 'department';
    holderId?: string | null;
  },
): AssetBulkChanges | null {
  switch (action) {
    case 'edit': {
      const changes: AssetBulkChanges = {};
      if (form.location.trim() !== '') changes.location = form.location.trim();
      if (form.costCentre.trim() !== '') changes.cost_centre = form.costCentre.trim();
      if (form.glCode.trim() !== '') changes.gl_code = form.glCode.trim();
      if (form.siteId !== undefined) changes.site_id = form.siteId;
      return Object.keys(changes).length === 0 ? null : changes;
    }
    case 'move':
      if (form.stateId === undefined) return null;
      return form.reason.trim() === ''
        ? { to_state_id: form.stateId }
        : { to_state_id: form.stateId, reason: form.reason.trim() };
    case 'assign':
      if (form.holderKind === 'none') return {};
      if (form.holderId == null) return null;
      return { holder_kind: form.holderKind, holder_id: form.holderId };
    case 'delete':
      return {};
  }
}

// File format names and the row cap, sent as values so labels isolate them (the people import's
// rule: "UTF-8" typed into a right-to-left sentence would read "8-UTF").
export const WORDS = {
  csv: 'CSV (UTF-8)',
  xlsx: '.xlsx',
  utf8: 'UTF-8',
  max_rows: '20,000',
  max_mb: '25',
};

const BOM = String.fromCharCode(0xfeff); // Excel reads the file as UTF-8 with it

/** A column's name in words (never its code). */
export function columnText(t: T, field: string | null | undefined): string {
  if (field == null || field === 'row') return t('assets.import.whole_row');
  const key = `asset_import_column.${field}`;
  return key in en ? t(key) : t('assets.import.whole_row');
}

/** Why the whole file was refused, in words. */
export function failureText(t: T, job: AssetImport): string {
  const code = job.failure ?? 'unexpected';
  const key = `asset_import_failure.${code}`;
  const detail = job.failure_detail ?? '';
  return key in en
    ? t(key, { ...WORDS, detail, column: columnText(t, detail) })
    : t('asset_import_failure.unexpected');
}

/** The rows with problems as a CSV file in the person's language (the error file, AC1). */
export function problemsCsv(t: T, problems: AssetImportProblem[]): string {
  const quote = (value: string) => `"${value.replaceAll('"', '""')}"`;
  const lines = [
    [t('assets.import.row'), t('assets.import.column'), t('assets.import.problem')].map(quote),
    ...problems.map((p) =>
      [String(p.row ?? ''), columnText(t, p.field), reasonText(t, p.code, p.field)].map(quote),
    ),
  ];
  return `${BOM}${lines.map((cells) => cells.join(',')).join('\r\n')}\r\n`;
}

export const EXPORT_COLUMNS = [
  'tag',
  'name',
  'product_id',
  'product_type_id',
  'state_id',
  'site_id',
  'serial_number',
  'vendor_id',
  'acquired_on',
  'warranty_expires_on',
  'cost_centre',
  'gl_code',
];
export const MONEY_COLUMNS = ['purchase_price', 'purchase_tax', 'book_value', 'total_cost'];

/** The export's columns for this person: money only with the right to see it. */
export function exportColumns(seesMoney: boolean): string[] {
  return seesMoney ? [...EXPORT_COLUMNS, ...MONEY_COLUMNS] : [...EXPORT_COLUMNS];
}
