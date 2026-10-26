import { useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import { queryKeys, useIncidentCatalogue, useIncidentSearch } from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { useAppearance, useLabel, type PaletteRecords } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { personName, statusLabel } from './labels';
import { recentIncidents } from './recent';

/**
 * Incidents for the command palette (Ctrl+K, REQ-INC-085): recently viewed ones while nothing is
 * typed, then everything the user may see that matches, best first (ID, words, requester).
 * Undefined when the user cannot see incidents: the palette then offers pages only.
 */
export function usePaletteIncidents(
  open: boolean,
  query: string,
  userId: string | null,
  allowed: boolean,
): PaletteRecords | undefined {
  const t = useLabel();
  const { locale } = useAppearance();
  const text = useDebounced(query.trim());
  const active = open && allowed;
  // Read when the palette opens: the record just left is the first recent one.
  const recentIds = useMemo(() => (open ? recentIncidents(userId) : []), [open, userId]);
  const found = useIncidentSearch(text === '' ? { ids: recentIds } : { q: text, limit: 8 }, active);
  const catalogue = useIncidentCatalogue(active);
  // Live while open: a record changed or created elsewhere updates the results (§8).
  const queryClient = useQueryClient();
  useListChannel(active ? 'incidents' : null, () => {
    refreshList(queryClient, [...queryKeys.incidents.all, 'list', 'search']);
  });
  return useMemo(() => {
    if (!allowed) return undefined;
    const people = found.data?.people ?? {};
    const items = [...(found.data?.items ?? [])];
    if (text === '') items.sort((a, b) => recentIds.indexOf(a.id) - recentIds.indexOf(b.id));
    return {
      title: t(text === '' ? 'search.recent' : 'search.incidents'),
      loading: found.isFetching,
      items: items.map((item) => ({
        key: `incident-${item.display_id}`,
        title: `${item.display_id} · ${item.subject}`,
        subtitle: [
          personName(people, item.requester_id),
          statusLabel(t, catalogue.data, item.status, locale),
        ]
          .filter((part) => part !== '')
          .join(' · '),
        path: `/incidents/${item.id}`,
      })),
    };
  }, [allowed, found.data, found.isFetching, text, recentIds, t, catalogue.data, locale]);
}
