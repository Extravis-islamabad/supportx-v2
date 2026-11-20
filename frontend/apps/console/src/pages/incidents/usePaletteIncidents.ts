import { useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import {
  queryKeys,
  useAliasLookup,
  useIncidentCatalogue,
  useIncidentSearch,
} from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { useAppearance, useLabel, type PaletteRecords } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { personName, statusLabel } from './labels';
import { recentIncidents } from './recent';
import { useHiddenPersonLabel } from '../../maskedPeople';

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
  const hidden = useHiddenPersonLabel();
  const t = useLabel();
  const { locale } = useAppearance();
  const text = useDebounced(query.trim());
  const active = open && allowed;
  // Read when the palette opens and whenever the box is cleared, so a record opened meanwhile
  // is offered too.
  const showRecent = text === '';
  const recentIds = useMemo(
    () => (open && showRecent ? recentIncidents(userId) : []),
    [open, showRecent, userId],
  );
  const found = useIncidentSearch(text === '' ? { ids: recentIds } : { q: text, limit: 8 }, active);
  const catalogue = useIncidentCatalogue(active);
  // An old number of a converted record leads to the new one (WP-046b S2, REQ-INC-089).
  const alias = useAliasLookup(text, active).data ?? null;
  // Live while open: a record changed or created elsewhere updates the results (§8).
  const queryClient = useQueryClient();
  useListChannel(active ? 'incidents' : null, () => {
    refreshList(queryClient, [...queryKeys.incidents.all, 'list', 'search']);
  });
  return useMemo(() => {
    if (!allowed) return undefined;
    const people = found.data?.people ?? {};
    // Results kept from the last search are not recent records: show none until they load.
    const stale = text === '' && (recentIds.length === 0 || found.isPlaceholderData);
    const items = stale ? [] : [...(found.data?.items ?? [])];
    if (text === '') items.sort((a, b) => recentIds.indexOf(a.id) - recentIds.indexOf(b.id));
    return {
      title: t(text === '' ? 'search.recent' : 'search.incidents'),
      loading: found.isFetching,
      items: [
        // An old number leads to the record it became, first (unless it is listed already).
        ...(alias === null || items.some((item) => item.id === alias.record_id)
          ? []
          : [
              {
                key: `alias-${alias.display_id}`,
                title: t('incidents.alias.moved', {
                  old: text.toUpperCase(),
                  id: alias.display_id,
                }),
                path: `/${alias.record_type === 'service_request' ? 'requests' : 'incidents'}/${alias.record_id}`,
              },
            ]),
        ...items.map((item) => ({
          key: `incident-${item.display_id}`,
          title: `${item.display_id} · ${item.subject}`,
          subtitle: [
            personName(people, item.requester_id, hidden),
            statusLabel(t, catalogue.data, item.status, locale),
          ]
            .filter((part) => part !== '')
            .join(' · '),
          path: `/incidents/${item.id}`,
        })),
      ],
    };
  }, [
    allowed,
    hidden,
    alias,
    found.data,
    found.isFetching,
    found.isPlaceholderData,
    text,
    recentIds,
    t,
    catalogue.data,
    locale,
  ]);
}
