import { useInfiniteQuery, useQuery } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// A CI's linked work items (WP-053 S5c, REQ-CMDB-019), for its Associations tab: per type, open
// and all, counting only the records you may see (D-158), and each type's list. Until work items
// offer the links the API answers `linked_records_not_available` and the tab stays hidden. Live
// through the CI's channel (field `linked`).
export type CiLinkedKinds = components['schemas']['CiLinkedKindsOut'];
export type CiLinkedKind = components['schemas']['CiLinkedKindOut'];
export type CiLinkedRecord = components['schemas']['CiLinkedRecordOut'];

/** Open and total per work-item type linked to the CI. */
export function useCiLinked(ciId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.cmdb.linked(ciId),
    queryFn: () =>
      call(api.GET('/api/v1/cmdb/cis/{ci_id}/linked', { params: { path: { ci_id: ciId } } })),
    enabled,
    // A tab of the CI page: "not available" hides it, and the page reports a CI it can't load.
    meta: { silent: true },
    retry: false,
  });
}

/** One type's linked work items you may see, newest first. */
export function useCiLinkedPage(ciId: string, kind: string | undefined) {
  return useInfiniteQuery({
    queryKey: [...queryKeys.cmdb.linked(ciId), kind ?? ''] as const,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/cmdb/cis/{ci_id}/linked/{kind}', {
          params: {
            path: { ci_id: ciId, kind: kind ?? '' },
            query: { cursor: pageParam ?? undefined },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: kind !== undefined,
    meta: { silent: true },
  });
}
