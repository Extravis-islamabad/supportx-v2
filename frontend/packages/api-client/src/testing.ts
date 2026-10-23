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
];
const ADMIN_EXTRA: Grant[] = [
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
