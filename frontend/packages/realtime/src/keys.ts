/** Query keys of this package (the list-channel lookups); refreshed after access changes. */
export const REALTIME_KEY = ['realtime'] as const;

export function listChannelsKey(tenantId: string, list: string) {
  return [...REALTIME_KEY, 'lists', tenantId, list] as const;
}
