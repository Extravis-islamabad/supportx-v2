import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { queryKeys } from '@supportx/api-client';
import { refreshList, useListChannel } from '@supportx/realtime';

/** Reports and widgets refresh at most once a second however busy the list they count is. */
export const LIVE_REFRESH_MS = 1000;

/**
 * Live numbers (rule c, REQ-RPT-008 AC2, REQ-DSH-016): every report run on screen refreshes when
 * the list it counts changes. The list channels are the viewer's own (scope-partitioned), so a
 * viewer never hears of records outside their scope. Many widgets on one dashboard share the one
 * refresh: it refetches every run at once, at most once a second.
 */
export function useLiveReportRefresh(listPath: string | null): void {
  const queryClient = useQueryClient();
  const last = useRef(0);
  const pending = useRef<number | null>(null);
  useListChannel(listPath, () => {
    const wait = Math.max(0, last.current + LIVE_REFRESH_MS - Date.now());
    if (pending.current !== null) return;
    pending.current = window.setTimeout(() => {
      pending.current = null;
      last.current = Date.now();
      refreshList(queryClient, queryKeys.reports.runs);
    }, wait);
  });
  useEffect(
    () => () => {
      if (pending.current !== null) window.clearTimeout(pending.current);
    },
    [],
  );
}
