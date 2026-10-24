/**
 * Test helpers (import from '@supportx/api-client/testing'): typed fixtures and a fake API that
 * replaces global fetch. Never imported by app code.
 */
import type { Entitlements } from './entitlements';
import type { components } from './schema';
import type { MeResponse } from './session';

export type UserDetail = components['schemas']['UserDetail'];

export const DEMO_TENANT = { id: '01900000-0000-7000-8000-00000000de30', name: 'Demo Company' };
export const OTHER_TENANT = { id: '01900000-0000-7000-8000-00000000a7e2', name: 'Other Company' };

type Grant = [
  string,
  MeResponse['permissions'] extends (infer P)[] | undefined
    ? P extends { scope: infer S }
      ? S
      : never
    : never,
];

const TECHNICIAN: Grant[] = [
  ['profile.edit', 'own'],
  ['users.view', 'all'],
  ['sites.view', 'all'],
  ['groups.view', 'all'],
  ['requests.view', 'all'],
  ['requests.create', 'all'],
  ['requests.edit', 'all'],
  ['requests.assign', 'all'],
  ['requests.close', 'all'],
  ['problems.view', 'all'],
  ['problems.manage', 'group'],
  ['changes.view', 'all'],
  ['changes.create', 'all'],
  ['releases.view', 'all'],
  ['assets.view', 'all'],
  ['assets.manage', 'group'],
  ['cmdb.view', 'all'],
  ['knowledge.view', 'all'],
  ['knowledge.manage', 'group'],
  ['reports.view', 'all'],
  ['announcements.view', 'all'],
  ['announcements.manage', 'own'],
  // D-052: technicians work on incidents at group scope (their groups, assigned, site queue).
  ['incidents.view', 'group'],
  ['incidents.create', 'all'],
  ['incidents.edit', 'group'],
  ['incidents.assign', 'group'],
  ['incidents.take', 'group'],
  ['incidents.change_priority', 'group'],
  ['incidents.resolve', 'group'],
  ['incidents.close', 'group'],
  ['incidents.reopen', 'group'],
  ['incidents.cancel', 'group'],
];
const ADMIN_EXTRA: Grant[] = [
  ['announcements.manage', 'all'],
  ['announcements.publish', 'all'],
  ['users.manage', 'all'],
  ['roles.view', 'all'],
  ['roles.manage', 'all'],
  ['sites.manage', 'all'],
  ['groups.manage', 'all'],
  ['settings.manage', 'all'],
  ['licence.manage', 'all'],
  ['changes.approve', 'all'],
  ['releases.manage', 'all'],
  ['cmdb.manage', 'all'],
  ['problems.manage', 'all'],
  ['incidents.view', 'all'],
  ['incidents.edit', 'all'],
  ['incidents.assign', 'all'],
  ['incidents.assign_outside_group', 'all'],
  ['incidents.delete', 'all'],
  ['audit.view', 'all'],
  ['audit.export', 'all'],
  ['audit.verify', 'all'],
  ['audit.manage', 'all'],
];
const REQUESTER: Grant[] = [
  ['profile.edit', 'own'],
  ['requests.view', 'own'],
  ['requests.create', 'all'],
  ['requests.close', 'own'],
  ['knowledge.view', 'all'],
];

/** Effective permissions like GET /auth/me returns for the system roles (mirrors the backend). */
export function fakePermissions(
  role: 'tenant_admin' | 'technician' | 'requester',
): NonNullable<MeResponse['permissions']> {
  const grants =
    role === 'requester'
      ? REQUESTER
      : role === 'technician'
        ? TECHNICIAN
        : [...TECHNICIAN, ...ADMIN_EXTRA];
  const byKey = new Map(grants.map(([key, scope]) => [key, scope]));
  return [...byKey.entries()].map(([key, scope]) => ({
    key,
    scope,
    scopes: [scope],
    conditional: false,
  }));
}

/** An announcement as staff see it (GET /announcements/{id}): a draft unless overridden. */
export function fakeAnnouncement(
  overrides: Partial<components['schemas']['AnnouncementOut']> = {},
): components['schemas']['AnnouncementOut'] {
  return {
    kind: 'staff',
    id: '01900000-0000-7000-8000-00000000a001',
    display_id: 'ANN-1',
    title: 'Mail outage',
    body: 'Mail is down.\nWe are on it.',
    severity: 'warning',
    status: 'draft',
    audience: 'everyone',
    site_ids: [],
    group_ids: [],
    owner_id: '01900000-0000-7000-8000-000000000101',
    show_as_banner: true,
    publish_from: null,
    publish_until: null,
    published_at: null,
    published_by: null,
    created_at: '2026-10-23T09:00:00Z',
    created_by: '01900000-0000-7000-8000-000000000101',
    updated_at: '2026-10-23T09:00:00Z',
    updated_by: '01900000-0000-7000-8000-000000000101',
    version: 1,
    visibility: 'hidden',
    next_change_in_seconds: null,
    actions: [
      { action: 'publish', allowed: true, reason: null },
      { action: 'unpublish', allowed: false, reason: 'not_from_status' },
      { action: 'archive', allowed: true, reason: null },
      { action: 'reopen', allowed: false, reason: 'not_from_status' },
    ],
    history_count: 1,
    can_manage: true,
    ...overrides,
  };
}

/** A session as GET /api/v1/auth/me returns it (a technician unless overridden). */
export function fakeSession(
  user: Partial<MeResponse['user']> = {},
  extra: Partial<Omit<MeResponse, 'user'>> = {},
): MeResponse {
  const roles = user.roles ?? ['technician'];
  const role = roles.includes('tenant_admin')
    ? 'tenant_admin'
    : roles.includes('technician')
      ? 'technician'
      : 'requester';
  return {
    user: {
      id: '01900000-0000-7000-8000-000000000101',
      email: 'tech@demo.test',
      display_name: 'Tariq Technician',
      locale: 'en',
      user_type: 'technician',
      roles: ['technician'],
      nav_layout: 'top',
      ...user,
    },
    tenant: DEMO_TENANT,
    tenants: [DEMO_TENANT],
    csrf_token: 'csrf-from-session',
    permissions: fakePermissions(role),
    ...extra,
  };
}

/** GET /entitlements for an active Enterprise plan unless overridden. */
export function fakeEntitlements(overrides: Partial<Entitlements> = {}): Entitlements {
  return {
    edition: 'enterprise',
    state: 'active',
    state_reason: null,
    writable: true,
    grace_ends_at: null,
    days_left: null,
    admin_warning: false,
    features: [
      'incident',
      'service_request',
      'knowledge',
      'sla',
      'ai_assist',
      'problem',
      'change',
      'release',
      'catalog',
      'cmdb',
      'assets',
      'discovery',
      'procurement',
      'workflows',
      'ai_agents',
      'monetx_integration',
      'projects',
      'esm',
      'msp',
    ],
    limits: [{ key: 'technicians', limit: 250, used: 3, remaining: 247 }],
    term: {
      starts_at: '2026-01-01T00:00:00Z',
      expires_at: null,
      maintenance_until: null,
      grace_days: 14,
    },
    ...overrides,
  };
}

export function fakeUser(overrides: Partial<UserDetail> = {}): UserDetail {
  return {
    id: '01900000-0000-7000-8000-000000000101',
    email: 'tech@demo.test',
    display_name: 'Tariq Technician',
    user_type: 'technician',
    status: 'active',
    locale: 'en',
    time_zone: null,
    signature: null,
    nav_layout: 'top',
    last_login_at: '2026-10-20T08:00:00Z',
    created_at: '2026-10-01T08:00:00Z',
    updated_at: '2026-10-20T08:00:00Z',
    version: 3,
    ...overrides,
  };
}

/** RFC 9457 body for a fake error response. */
export function problem(
  status: number,
  code: string,
  extra: Partial<components['schemas']['ProblemDetail']> = {},
): components['schemas']['ProblemDetail'] {
  return {
    type: `urn:supportx:problem:${code}`,
    title: code,
    status,
    code,
    message_key: `errors.${code}`,
    params: {},
    errors: [],
    request_id: 'req-0001',
    ...extra,
  };
}

export interface RecordedCall {
  method: string;
  path: string;
  url: URL;
  headers: Headers;
  body: unknown;
}

export type FakeReply =
  { status?: number; body?: unknown; headers?: Record<string, string> } | 'network-error';
export type FakeRoute = FakeReply | ((call: RecordedCall) => FakeReply | Promise<FakeReply>);

/**
 * Replace global fetch with a route table: `'GET /api/v1/auth/me': {body: fakeSession()}`.
 * Unknown routes answer 404 problem details. Returns the recorded calls and a restore function.
 */
export function fakeApi(routes: Record<string, FakeRoute>) {
  const calls: RecordedCall[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    const text = request.method === 'GET' || request.method === 'HEAD' ? '' : await request.text();
    const call: RecordedCall = {
      method: request.method,
      path: url.pathname,
      url,
      headers: request.headers,
      body: text === '' ? undefined : (JSON.parse(text) as unknown),
    };
    calls.push(call);
    const route = routes[`${request.method} ${url.pathname}`];
    const reply = typeof route === 'function' ? await route(call) : route;
    if (reply === 'network-error') throw new TypeError('Failed to fetch');
    if (reply === undefined) {
      return new Response(JSON.stringify(problem(404, 'not_found')), { status: 404 });
    }
    const status = reply.status ?? 200;
    const body = status === 204 || reply.body === undefined ? null : JSON.stringify(reply.body);
    return new Response(body, {
      status,
      headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'req-0001', ...reply.headers },
    });
  };
  return {
    calls,
    find: (method: string, path: string) =>
      calls.filter((c) => c.method === method && c.path === path),
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

type Incident = components['schemas']['WorkItemOut'];
type IncidentCatalogue = components['schemas']['WorkItemCatalogueOut'];

const INCIDENT_ACTIONS = [
  'start_work',
  'wait_requester',
  'wait_third_party',
  'resume',
  'resolve',
  'close',
  'reopen',
  'cancel',
  'undo_cancel',
] as const;
const FROM_NEW = new Set(['start_work', 'resolve', 'cancel']);

/** An incident as staff see it (GET /incidents/{id}): new, unassigned, at a site, P3 default. */
export function fakeIncident(overrides: Partial<Incident> = {}): Incident {
  const requester = '01900000-0000-7000-8000-0000000002a1';
  return {
    id: '01900000-0000-7000-8000-00000000c001',
    type: 'incident',
    display_id: 'INC-7',
    subject: 'Mail is down',
    description: '<p>Since <strong>9:00</strong>.</p>',
    requester_id: requester,
    on_behalf_of_id: null,
    channel: 'phone',
    site_id: null,
    group_id: null,
    technician_id: null,
    category_id: null,
    impact: null,
    urgency: null,
    priority: 'p3',
    priority_source: 'default',
    status: 'new',
    status_category: 'open',
    status_reason_code: null,
    status_reason_text: null,
    status_changed_at: '2026-10-24T09:00:00Z',
    tags: [],
    first_assigned_at: null,
    first_responded_at: null,
    resolved_at: null,
    closed_at: null,
    last_reopened_at: null,
    reopen_count: 0,
    reassignment_count: 0,
    paused_seconds: 0,
    paused_since: null,
    sla_policy_id: null,
    first_response_due_at: null,
    resolution_due_at: null,
    created_at: '2026-10-24T09:00:00Z',
    created_by: requester,
    updated_at: '2026-10-24T09:00:00Z',
    updated_by: requester,
    version: 1,
    actions: INCIDENT_ACTIONS.map((action) => ({
      action,
      allowed: FROM_NEW.has(action),
      reason: FROM_NEW.has(action) ? null : 'not_from_status',
      reason_mode: action === 'cancel' ? 'required' : 'none',
      reason_list: action === 'cancel' ? 'cancel' : null,
    })),
    operations: ['edit', 'assign', 'take', 'change_priority', 'delete'].map((action) => ({
      action,
      allowed: action !== 'delete',
      reason: action === 'delete' ? 'no_permission' : null,
      reason_mode: 'none',
      reason_list: null,
    })),
    history_count: 1,
    people: { [requester]: { display_name: 'Rana Requester', email: 'rana@demo.test' } },
    visible: true,
    ...overrides,
  };
}

/** GET /incidents/settings: the Appendix A defaults. */
export function fakeIncidentCatalogue(): IncidentCatalogue {
  const impacts = ['one_person', 'team', 'department_or_site', 'organisation'] as const;
  const urgencies = ['low', 'medium', 'high', 'critical'] as const;
  const rows = [
    ['p4', 'p4', 'p3', 'p3'],
    ['p4', 'p3', 'p3', 'p2'],
    ['p3', 'p3', 'p2', 'p1'],
    ['p3', 'p2', 'p1', 'p1'],
  ] as const;
  return {
    prefix: 'INC',
    default_priority: 'p3',
    auto_status_on_assign: true,
    version: 1,
    statuses: [
      ['new', 'open'],
      ['assigned', 'open'],
      ['in_progress', 'open'],
      ['awaiting_requester', 'paused'],
      ['resolved', 'resolved'],
      ['closed', 'closed'],
      ['canceled', 'canceled'],
    ].map(([code, category]) => ({
      code: code ?? '',
      category: category as IncidentCatalogue['statuses'][number]['category'],
      colour: '#1677ff',
      labels: null,
      system: false,
      disabled: false,
    })),
    actions: [...INCIDENT_ACTIONS],
    transitions: [],
    scales: [],
    matrix: impacts.flatMap((impact, i) =>
      urgencies.map((urgency, j) => ({ impact, urgency, priority: rows[i]?.[j] ?? 'p3' })),
    ),
    reasons: [
      { list: 'cancel', code: 'duplicate', labels: null },
      { list: 'cancel', code: 'other', labels: null },
      { list: 'reassign', code: 'wrong_group', labels: null },
    ],
  };
}

type AuditStatus = components['schemas']['AuditStatusOut'];

/** GET /audit/status for a healthy chain (no alert) unless overridden. */
export function fakeAuditStatus(overrides: Partial<AuditStatus> = {}): AuditStatus {
  return {
    sealed_entries: 120,
    pending_seal: 0,
    pending_overdue: 0,
    anchoring_configured: true,
    last_anchor_at: '2026-10-24T09:00:00Z',
    last_anchor_seq: 118,
    last_daily: null,
    last_weekly: null,
    last_on_demand: null,
    alert: null,
    ...overrides,
  };
}
