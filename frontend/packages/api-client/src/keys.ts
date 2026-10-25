import type { AnnouncementsQuery } from './announcements';
import type { AuditEntriesQuery } from './audit';
import type { IncidentsQuery } from './incidents';
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
  announcements: {
    all: ['announcements'] as const,
    list: (query: AnnouncementsQuery) => ['announcements', 'list', query] as const,
    detail: (id: string) => ['announcements', 'detail', id] as const,
    history: (id: string) => ['announcements', 'history', id] as const,
    feed: ['announcements', 'feed'] as const,
    settings: ['announcements', 'settings'] as const,
    ownerCandidates: (search: string, include: string | null) =>
      ['announcements', 'owner-candidates', search, include] as const,
  },
  incidents: {
    all: ['incidents'] as const,
    list: (query: IncidentsQuery) => ['incidents', 'list', query] as const,
    views: ['incidents', 'views'] as const,
    detail: (id: string) => ['incidents', 'detail', id] as const,
    history: (id: string, actors: string) => ['incidents', 'history', id, actors] as const,
    catalogue: ['incidents', 'catalogue'] as const,
    categories: ['incidents', 'categories'] as const,
    assignees: (groupId: string | null, search: string) =>
      ['incidents', 'assignees', groupId, search] as const,
  },
  audit: {
    all: ['audit'] as const,
    list: (query: AuditEntriesQuery) => ['audit', 'list', query] as const,
    entry: (id: string) => ['audit', 'entry', id] as const,
    status: ['audit', 'status'] as const,
    runs: ['audit', 'runs'] as const,
    settings: ['audit', 'settings'] as const,
    exports: ['audit', 'exports'] as const,
    saved: ['audit', 'saved'] as const,
    archives: ['audit', 'archives'] as const,
    restored: (id: string) => ['audit', 'restored', id] as const,
  },
  users: {
    all: ['users'] as const,
    list: (query: UsersQuery) => ['users', 'list', query] as const,
    detail: (id: string) => ['users', 'detail', id] as const,
  },
};
