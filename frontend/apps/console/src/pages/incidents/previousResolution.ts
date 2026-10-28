import { useIncidentHistory, type Incident } from '@supportx/api-client';

/**
 * The resolution an incident had before it was reopened (D-107: re-resolving offers to reuse
 * it; history keeps both). From the history the record page already loads: the newest change
 * of the resolution whose old value had words.
 */
export function usePreviousResolution(item: Incident): string | null {
  const wanted = item.reopen_count > 0 && item.resolution === null;
  const history = useIncidentHistory(item.id, 'all', wanted);
  if (!wanted) return null;
  for (const page of history.data?.pages ?? []) {
    for (const entry of page.items) {
      for (const change of entry.changes) {
        if (change.field === 'resolution' && typeof change.old === 'string' && change.old !== '') {
          return change.old;
        }
      }
    }
  }
  return null;
}
