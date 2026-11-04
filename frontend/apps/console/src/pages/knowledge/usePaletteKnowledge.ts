import { useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import { queryKeys, useKbArticles } from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';
import { useAppearance, useLabel, type PaletteRecords } from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { articleLanguage } from './model';

/**
 * Knowledge in the command palette (REQ-KB-053, D-125): published articles you may read that
 * match what is typed, beside incidents. The article list's own search, so the palette never
 * offers what the list would hide. Nothing while the box is empty (no "recent" articles).
 */
export function usePaletteKnowledge(
  open: boolean,
  query: string,
  allowed: boolean,
): PaletteRecords | undefined {
  const t = useLabel();
  const { locale } = useAppearance();
  const text = useDebounced(query.trim());
  const active = open && allowed && text.length >= 2;
  const found = useKbArticles(
    { view: 'published', language: articleLanguage(locale), search: text },
    active,
  );
  const queryClient = useQueryClient();
  useListChannel(active ? 'knowledge' : null, () => {
    refreshList(queryClient, [...queryKeys.knowledge.all, 'list']);
  });
  return useMemo(() => {
    if (!allowed || !active) return undefined;
    return {
      title: t('search.knowledge'),
      loading: found.isFetching,
      items: (found.data ?? []).slice(0, 6).map((row) => {
        // Where the words were found, as plain text (the palette shows no marks).
        const snippet = (row.snippet ?? []).map((part) => part.text).join('');
        return {
          key: `kb-${row.display_id}`,
          title: `${row.display_id} · ${row.title}`,
          subtitle: snippet === '' ? undefined : snippet,
          path: `/knowledge/articles/${row.id}`,
        };
      }),
    };
  }, [allowed, active, found.data, found.isFetching, t]);
}
