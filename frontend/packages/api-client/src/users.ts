import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call, rememberEtag } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

export type UserDetail = components['schemas']['UserDetail'];
export type UserPage = components['schemas']['UserPage'];
export type UserPreferencesPatch = components['schemas']['UserPreferencesPatch'];
export type FilterExpression = components['schemas']['FilterExpression'];
export type FilterCondition = components['schemas']['FilterCondition'];

/** List parameters the UI controls; `filter` is the shared JSON filter DSL (architecture.md §6.5). */
export interface UsersQuery {
  filter?: FilterExpression;
  /** e.g. `display_name` or `-last_login_at` */
  sort?: string;
  limit?: number;
}

/** Free-text search as a filter DSL expression over name and email. */
export function searchFilter(text: string): FilterExpression | undefined {
  const value = text.trim();
  if (value === '') return undefined;
  return {
    or: [
      { field: 'display_name', op: 'contains', value },
      { field: 'email', op: 'contains', value },
    ],
  };
}

/** AND the non-empty parts together (undefined when there is nothing to filter on). */
export function allOf(...parts: (FilterExpression | undefined)[]): FilterExpression | undefined {
  const present = parts.filter((part): part is FilterExpression => part !== undefined);
  if (present.length === 0) return undefined;
  return present.length === 1 ? present[0] : { and: present };
}

/** GET /users with cursor pagination: `fetchNextPage()` follows `next_cursor`. */
export function useUsers(query: UsersQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.users.list(query),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/users', {
          params: {
            query: {
              filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
              sort: query.sort,
              limit: query.limit ?? 50,
              cursor: pageParam ?? undefined,
              include_total: pageParam === null,
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

/** One user; its ETag is remembered by the client for the next PATCH (If-Match). */
export function useUser(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.users.detail(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/users/{user_id}', { params: { path: { user_id: id ?? '' } } })),
    enabled: id !== undefined,
  });
}

/**
 * PATCH /users/{id} (own signature / time zone). Sends If-Match for the version the form was
 * loaded from, so a concurrent change answers 409 `version_conflict` instead of being lost.
 */
export function useUpdateUser(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    // The form shows these errors itself (inline, conflict dialog), so no global toast.
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: UserPreferencesPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/users/{user_id}', {
          params: { path: { user_id: id }, header: { 'If-Match': `"${String(version)}"` } },
          body: changes,
        }),
      ),
    onSuccess: (user) => {
      rememberEtag(`/api/v1/users/${id}`, `"${String(user.version)}"`);
      queryClient.setQueryData(queryKeys.users.detail(id), user);
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.users.all, 'list'] });
    },
  });
}
