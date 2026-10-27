import type { AnnouncementsQuery } from './announcements';
import type { AuditEntriesQuery } from './audit';
import type { IncidentSearchQuery, IncidentsQuery } from './incidents';
import type { ReportDefinition } from './reports';
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
  // The server version for the About dialog (same endpoint as health, different data shape).
  version: ['system', 'version'] as const,
  access: {
    all: ['access'] as const,
    catalogue: ['access', 'catalogue'] as const,
    roles: ['access', 'roles'] as const,
    role: (id: string) => ['access', 'roles', id] as const,
    user: (id: string) => ['access', 'user', id] as const,
    units: (kind: 'sites' | 'groups') => ['access', kind] as const,
  },
  identity: {
    all: ['identity'] as const,
    settings: ['identity', 'settings'] as const,
    sso: ['identity', 'sso'] as const,
    invitations: ['identity', 'invitations'] as const,
    personInvitations: (userId: string) => ['identity', 'invitations', userId] as const,
    test: (id: string, testId: string) => ['identity', 'sso', id, 'test', testId] as const,
  },
  branding: {
    all: ['branding'] as const,
    public: ['branding', 'public'] as const,
    current: ['branding', 'current'] as const,
    settings: ['branding', 'settings'] as const,
    domains: ['branding', 'domains'] as const,
    check: (primary: string | null, gradient: readonly [string, string] | null) =>
      ['branding', 'check', primary, gradient] as const,
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
  reports: {
    all: ['reports'] as const,
    library: ['reports', 'library'] as const,
    entity: (entity: string) => ['reports', 'entity', entity] as const,
    detail: (id: string) => ['reports', 'detail', id] as const,
    // Every run, so a list signal can refresh all reports on screen at once.
    runs: ['reports', 'run'] as const,
    run: (definition: ReportDefinition | undefined) => ['reports', 'run', definition] as const,
  },
  incidents: {
    all: ['incidents'] as const,
    list: (query: IncidentsQuery) => ['incidents', 'list', query] as const,
    // Under 'list': whatever refreshes the lists refreshes searches (WP-027).
    search: (query: IncidentSearchQuery) => ['incidents', 'list', 'search', query] as const,
    views: ['incidents', 'views'] as const,
    detail: (id: string) => ['incidents', 'detail', id] as const,
    history: (id: string, actors: string) => ['incidents', 'history', id, actors] as const,
    // Under the record's history: whatever refreshes the history refreshes this (WP-029).
    automation: (id: string) => ['incidents', 'history', id, 'automation'] as const,
    catalogue: ['incidents', 'catalogue'] as const,
    categories: ['incidents', 'categories'] as const,
    assignees: (groupId: string | null, search: string) =>
      ['incidents', 'assignees', groupId, search] as const,
    conversation: (id: string) => ['incidents', 'conversation', id] as const,
    followers: (id: string) => ['incidents', 'followers', id] as const,
    counters: ['incidents', 'counters'] as const,
    replyTemplates: ['incidents', 'reply-templates'] as const,
    templates: ['incidents', 'templates'] as const,
  },
  customFields: {
    all: ['custom-fields'] as const,
    list: (entity: string, removed: boolean) => ['custom-fields', entity, removed] as const,
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
  files: {
    all: ['files'] as const,
    record: (recordType: string, recordId: string) =>
      ['files', 'record', recordType, recordId] as const,
    detail: (id: string) => ['files', 'detail', id] as const,
    rules: ['files', 'rules'] as const,
    usage: ['files', 'usage'] as const,
    status: ['files', 'status'] as const,
  },
  automation: {
    all: ['automation'] as const,
    fields: (recordType: string) => ['automation', 'fields', recordType] as const,
    rules: (recordType: string) => ['automation', 'rules', recordType] as const,
    routing: (recordType: string) => ['automation', 'routing', recordType] as const,
    routingSettings: (recordType: string) =>
      ['automation', 'routing-settings', recordType] as const,
    assignment: (groupId: string) => ['automation', 'assignment', groupId] as const,
    availability: (userIds: string[]) => ['automation', 'availability', ...userIds] as const,
    triggers: (recordType: string) => ['automation', 'triggers', recordType] as const,
    transitions: (recordType: string) => ['automation', 'transitions', recordType] as const,
    loopStops: ['automation', 'loop-stops'] as const,
  },
  organization: {
    all: ['organization'] as const,
    list: (kind: string) => ['organization', kind] as const,
  },
  people: {
    imports: ['users', 'imports'] as const,
    accessSettings: ['access', 'settings'] as const,
    reactivation: (id: string) => ['users', 'reactivation', id] as const,
  },
  users: {
    all: ['users'] as const,
    list: (query: UsersQuery) => ['users', 'list', query] as const,
    detail: (id: string) => ['users', 'detail', id] as const,
  },
};
