/**
 * Test helpers (import from '@supportx/api-client/testing'): typed fixtures and a fake API that
 * replaces global fetch. Never imported by app code.
 */
import type { ConversationEntry } from './conversation';
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
  ['knowledge.view', 'group'],
  ['knowledge.create', 'group'],
  ['knowledge.edit_own', 'own'],
  ['knowledge.submit', 'own'],
  ['reports.view', 'all'],
  ['reports.create', 'own'],
  ['dashboards.create', 'own'],
  ['reports.export', 'all'],
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
  ['files.manage', 'all'],
  ['announcements.manage', 'all'],
  ['announcements.publish', 'all'],
  ['users.manage', 'all'],
  ['roles.view', 'all'],
  ['roles.manage', 'all'],
  ['sites.manage', 'all'],
  ['groups.manage', 'all'],
  ['departments.view', 'all'],
  ['departments.manage', 'all'],
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
  ['automation.view', 'all'],
  ['automation.manage', 'all'],
  ['reports.manage_folders', 'all'],
  ['reports.schedule', 'all'],
  ['dashboards.share', 'all'],
  ['dashboards.manage_defaults', 'all'],
  ['identity.manage', 'all'],
  ['notifications.manage', 'all'],
  ['mailboxes.manage', 'all'],
];
const REQUESTER: Grant[] = [
  ['profile.edit', 'own'],
  ['requests.view', 'own'],
  ['requests.create', 'all'],
  ['requests.close', 'own'],
  ['knowledge.view', 'own'],
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
      form_density: 'comfortable',
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
    first_name: 'Tariq',
    last_name: 'Technician',
    name_custom: false,
    employee_id: null,
    job_title: null,
    phone: null,
    mobile: null,
    vip: false,
    site_id: null,
    department_id: null,
    manager_id: null,
    can_sign_in: true,
    signed_in_before: true,
    request_visibility: null,
    user_type: 'technician',
    status: 'active',
    locale: 'en',
    time_zone: null,
    signature: null,
    nav_layout: 'top',
    form_density: 'comfortable',
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
    custom: {},
    requester_id: requester,
    on_behalf_of_id: null,
    channel: 'phone',
    site_id: null,
    department_id: null,
    desk_id: '01900000-0000-7000-8000-0000000000d1',
    group_id: null,
    technician_id: null,
    category_id: null,
    impact: null,
    impact_details: null,
    urgency: null,
    priority: 'p3',
    priority_source: 'default',
    level: null,
    template_id: STANDARD_TEMPLATE_ID,
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
    resolution: null,
    closure_code: null,
    resolution_notified_at: null,
    follows_id: null,
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
      // Resolve and close: record fields the closure rules still need (WP-020f).
      ...(action === 'resolve' || action === 'close' ? { missing: [] } : {}),
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
    conversation_actions: ['add_note', 'reply', 'manage_followers'].map((action) => ({
      action,
      allowed: true,
      reason: null,
      reason_mode: 'none',
      reason_list: null,
    })),
    following: false,
    conversation_count: 0,
    ...overrides,
  };
}

/** A note or reply on an incident (GET /incidents/{id}/conversation). */
export function fakeConversationEntry(
  overrides: Partial<ConversationEntry> = {},
): ConversationEntry {
  return {
    id: '01900000-0000-7000-8000-0000000c0e01',
    kind: 'note',
    visibility: 'private',
    reply_mode: null,
    body: '<p>Checked the mail server.</p>',
    recipients: null,
    delivery_state: null,
    delivery_reason: null,
    first_response: false,
    mentioned_ids: [],
    created_at: '2026-10-24T09:30:00Z',
    created_by: '01900000-0000-7000-8000-0000000000a1',
    version: 1,
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
    default_impact: 'team',
    default_urgency: 'medium',
    auto_status_on_assign: true,
    keep_following_on_handover: true,
    first_response_on: ['reply', 'public_note'],
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
      resume_on_requester_reply: code === 'awaiting_requester',
    })),
    actions: [...INCIDENT_ACTIONS],
    transitions: [],
    scales: [],
    matrix: impacts.flatMap((impact, i) =>
      urgencies.map((urgency, j) => ({ impact, urgency, priority: rows[i]?.[j] ?? 'p3' })),
    ),
    reasons: (
      [
        ['cancel', 'duplicate'],
        ['cancel', 'other'],
        ['reassign', 'wrong_group'],
        ['reassign', 'other'],
        ['pause', 'other'],
      ] as const
    ).map(([list, code], sort_order) => ({
      list,
      code,
      labels: null,
      sort_order,
      colour: null,
      disabled: false,
    })),
    levels: ['tier_1', 'tier_2', 'tier_3', 'tier_4'].map((code, sort_order) => ({
      code,
      labels: null,
      sort_order,
      colour: null,
      disabled: false,
    })),
    closure_codes: ['fixed', 'workaround', 'no_fault_found', 'duplicate', 'user_error'].map(
      (code, sort_order) => ({ code, labels: null, sort_order, colour: null, disabled: false }),
    ),
    // WP-020f defaults (D1, D2, D5): auto-close off until a channel tells requesters.
    closure: {
      resolve_requires: ['resolution'],
      close_requires: ['closure_code'],
      open_work: { tasks: 'warn', checklists: 'warn', child_incidents: 'warn', approvals: 'block' },
      complete_open_work: false,
      auto_close_days: null,
      reopen_window_days: 7,
      task_owner_access: false, // WP-020e (D-112): off by default
      requester_channels: [],
      requester_channel_states: [],
    },
    next_number: 8,
  };
}

type IncidentTemplate = components['schemas']['TemplateOut'];
type TemplateFieldName = components['schemas']['TemplateField'];

export const STANDARD_TEMPLATE_ID = '01900000-0000-7000-8000-0000000007e1';
const TEMPLATE_FIELDS: TemplateFieldName[] = [
  'subject',
  'requester_id',
  'on_behalf_of_id',
  'channel',
  'site_id',
  'category_id',
  'level',
  'group_id',
  'technician_id',
  'impact',
  'urgency',
  'impact_details',
  'description',
  'tags',
];

/** GET /incidents/templates: the seeded standard template (every field shown), as the default. */
export function fakeIncidentTemplate(overrides: Partial<IncidentTemplate> = {}): IncidentTemplate {
  const fixed = new Set<TemplateFieldName>(['subject', 'requester_id']);
  return {
    id: STANDARD_TEMPLATE_ID,
    code: 'standard',
    labels: null,
    description: null,
    group_name: null,
    is_default: true,
    for_requesters: false,
    disabled: false,
    copied_from_id: null,
    fields: Object.fromEntries(
      TEMPLATE_FIELDS.map((name) => [
        name,
        {
          shown: true,
          required: fixed.has(name),
          requester_can_see: true,
          requester_can_fill: fixed.has(name) || name === 'description',
        },
      ]),
    ),
    custom_fields: {},
    defaults: {},
    version: 1,
    ...overrides,
  };
}

type CustomField = components['schemas']['CustomFieldOut'];

/** GET /custom-fields: one active incident field of `field_type` (text unless overridden). */
export function fakeCustomField(overrides: Partial<CustomField> = {}): CustomField {
  return {
    id: '01900000-0000-7000-8000-0000000c0f01',
    entity: 'incident',
    key: 'room',
    field_type: 'text',
    labels: { en: 'Room', ar: 'الغرفة' },
    help: null,
    choices: [],
    display: 'list',
    default: null,
    validation: {
      required: false,
      min: null,
      max: null,
      min_length: null,
      max_length: null,
      pattern: null,
    },
    currency: null,
    sort_order: 0,
    retired: false,
    removed: false,
    in_use: false,
    index_state: 'none',
    index_error: null,
    version: 1,
    ...overrides,
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

/** A stored file (GET /files/…): a clean PDF on an incident unless overridden (WP-022). */
export function fakeStoredFile(
  overrides: Partial<components['schemas']['FileOut']> = {},
): components['schemas']['FileOut'] {
  return {
    id: '01900000-0000-7000-8000-0000000f0001',
    name: 'invoice.pdf',
    size: 245_000,
    content_type: 'application/pdf',
    kind: 'pdf',
    state: 'clean',
    openable: true,
    previewable: true,
    has_thumbnail: false,
    owner_type: 'work_item',
    owner_id: '01900000-0000-7000-8000-000000000101',
    record_type: 'incident',
    record_id: '01900000-0000-7000-8000-000000000101',
    inline: false,
    uploaded_by: null,
    created_at: '2026-10-26T09:00:00Z',
    version: 1,
    ...overrides,
  };
}

/** The tenant's file rules (GET /files/settings/rules): the defaults unless overridden. */
export function fakeFileRules(
  overrides: Partial<components['schemas']['RulesOut']> = {},
): components['schemas']['RulesOut'] {
  return {
    max_file_mb: 25,
    max_batch: 20,
    blocked_extensions: ['bat', 'exe', 'js', 'msi', 'ps1', 'sh'],
    version: 0,
    ...overrides,
  };
}

type Branding = components['schemas']['BrandingOut'];

/** A tenant's brand (GET /organization/branding, /public/branding): the default unless overridden. */
export function fakeBranding(overrides: Partial<Branding> = {}): Branding {
  return {
    customised: false,
    primary_colour: '#7e40d1',
    gradient: ['#6060de', '#951ab6'],
    product_name: {},
    portal_name: {},
    welcome_text: {},
    logos: {},
    version: 0,
    ...overrides,
  };
}

/** Scanning status (GET /files/settings/status): a working scanner unless overridden. */
export function fakeFileStatus(
  overrides: Partial<components['schemas']['StatusOut']> = {},
): components['schemas']['StatusOut'] {
  return {
    scanner_installed: true,
    scanner_reachable: true,
    scan_required: true,
    signature_date: '2026-10-25T08:24:12Z',
    signatures_stale: false,
    waiting: 0,
    failed: 0,
    not_scanned: 0,
    warnings: [],
    ...overrides,
  };
}

/** A notification centre entry (GET /notifications): unread unless overridden. */
export function fakeNotification(
  overrides: Partial<components['schemas']['NotificationOut']> = {},
): components['schemas']['NotificationOut'] {
  return {
    id: '01900000-0000-7000-8000-00000000a001',
    event_code: 'incident.assigned',
    record_type: 'incident',
    record_id: '01900000-0000-7000-8000-0000000001c1',
    display_id: 'INC-12',
    title: 'INC-12 is assigned to Tariq Technician: Mail is down',
    link: '/incidents/01900000-0000-7000-8000-0000000001c1',
    urgent: false,
    read: false,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

/** An event's rule as the rules screen gets it (the shipped default unless overridden). */
export function fakeNotificationRule(
  overrides: Partial<components['schemas']['NotificationRuleOut']> = {},
): components['schemas']['NotificationRuleOut'] {
  return {
    event_code: 'incident.created',
    record_type: 'incident',
    category: 'created',
    required: false,
    is_default: true,
    enabled: true,
    recipients: ['requester'],
    channels: ['in_app', 'email'],
    user_ids: [],
    group_ids: [],
    conditions: [],
    notify_actor: false,
    default_enabled: true,
    default_recipients: ['requester'],
    recipient_kinds: ['requester', 'assignee', 'followers'],
    condition_fields: ['priority'],
    version: 0,
    updated_at: null,
    updated_by: null,
    ...overrides,
  };
}

/** A support mailbox (WP-024), working, with nothing held. */
export function fakeMailbox(
  overrides: Partial<components['schemas']['MailboxOut']> = {},
): components['schemas']['MailboxOut'] {
  return {
    id: '01900000-0000-7000-8000-000000000a01',
    address: 'it@acme.test',
    display_name: null,
    host: 'imap.acme.test',
    port: 993,
    security: 'tls',
    allow_plain: false,
    username: 'it@acme.test',
    has_password: true,
    folder: 'INBOX',
    after_fetch: 'mark_read',
    move_to: null,
    creates: 'incident',
    group_id: null,
    unknown_senders: 'create_allowed_domains',
    allowed_domains: ['acme.test'],
    enabled: true,
    state: 'working',
    state_reason: null,
    last_fetch_at: '2026-10-28T09:00:00Z',
    held: 0,
    version: 1,
    ...overrides,
  };
}
