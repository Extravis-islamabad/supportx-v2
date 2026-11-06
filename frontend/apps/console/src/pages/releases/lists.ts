import { useReleaseSettings } from '@supportx/api-client';

export const RISKS = ['low', 'medium', 'high'] as const;

/** One of the release type's own lists (types, reasons, downtime kinds), enabled values only. */
export function useOwnList(name: string) {
  const settings = useReleaseSettings();
  return (settings.data?.own_lists?.[name] ?? []).filter((v) => !v.disabled);
}
