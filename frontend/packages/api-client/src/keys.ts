import type { UsersQuery } from './users';

/**
 * Query keys, one convention for every resource: [resource, scope, ...params].
 *   ['users']                       everything about users (invalidate after any user change)
 *   ['users', 'list', {filters}]    one list query
 *   ['users', 'detail', id]         one record
 * Realtime events (WP-011) patch or invalidate by these same keys (architecture.md §8.3).
 */
export const queryKeys = {
  session: ['auth', 'me'] as const,
  entitlements: ['entitlements'] as const,
  health: ['system', 'health'] as const,
  access: {
    all: ['access'] as const,
    catalogue: ['access', 'catalogue'] as const,
    roles: ['access', 'roles'] as const,
    role: (id: string) => ['access', 'roles', id] as const,
    user: (id: string) => ['access', 'user', id] as const,
    units: (kind: 'sites' | 'groups') => ['access', kind] as const,
  },
  users: {
    all: ['users'] as const,
    list: (query: UsersQuery) => ['users', 'list', query] as const,
    detail: (id: string) => ['users', 'detail', id] as const,
  },
};
