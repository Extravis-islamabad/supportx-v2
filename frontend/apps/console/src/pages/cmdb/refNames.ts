import type { CiRefName } from '@supportx/api-client';

/** The server's names for a CI's references, by the referenced ID (CMDB polish). */
export type RefNames = Record<string, CiRefName>;

/**
 * A referenced site, group, person or asset by the name the server gave this reader: its label,
 * "Not shown to you", or "No longer exists". "Set" only when the answer carried no name for it;
 * never the ID (rule d).
 */
export function refText(
  t: (key: string) => string,
  names: RefNames | undefined,
  value: unknown,
): string {
  const name = typeof value === 'string' ? names?.[value] : undefined;
  if (name === undefined) return t('cmdb.versions.set');
  if (name.restricted) return t('layout.restricted_hidden');
  if (name.gone || name.label == null || name.label === '') return t('cmdb.versions.unknown');
  return name.label;
}
