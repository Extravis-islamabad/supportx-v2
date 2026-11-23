import {
  fakeBranding,
  fakeApi,
  fakeAuditStatus,
  fakeFileRules,
  fakeFileStatus,
  fakeEntitlements,
  fakeSession,
  fakeUser,
  type FakeRoute,
  type RecordedCall,
} from '@supportx/api-client/testing';
import type { MeResponse } from '@supportx/api-client';

export { fakeEntitlements, fakeSession, fakeUser, problem } from '@supportx/api-client/testing';

const ME = '/api/v1/users/01900000-0000-7000-8000-000000000101';

// The work-item lists ask by POST (lane C: a filter may hold a protected value, never in a URL);
// a test's GET list mock answers the POST form too, as the two give the same page.
const LISTS = /^GET (\/api\/v1\/(?:incidents|service-requests|problems|changes|releases))$/;

function listsByPost(routes: Record<string, FakeRoute>): Record<string, FakeRoute> {
  const mirrored: Record<string, FakeRoute> = {};
  for (const [key, route] of Object.entries(routes)) {
    const path = LISTS.exec(key)?.[1];
    if (path !== undefined && !(`POST ${path}/list` in routes)) {
      mirrored[`POST ${path}/list`] = route;
    }
  }
  return mirrored;
}

/**
 * The console's API: a signed-in technician on an active Enterprise plan unless overridden.
 * `me: null` = no session (401).
 */
export function consoleApi({
  me = fakeSession(),
  routes = {},
}: { me?: MeResponse | null; routes?: Record<string, FakeRoute> } = {}) {
  return fakeApi({
    'GET /api/v1/auth/me':
      me === null
        ? { status: 401, body: { code: 'unauthenticated', message_key: 'errors.unauthenticated' } }
        : { body: me },
    'POST /api/v1/auth/logout': { status: 204 },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/health': { body: { status: 'ok', version: '0.1.0' } },
    [`GET ${ME}`]: { body: fakeUser(), headers: { ETag: '"3"' } },
    'GET /api/v1/audit/status': { body: fakeAuditStatus() },
    'GET /api/v1/files/settings/status': { body: fakeFileStatus() },
    'GET /api/v1/files/settings/rules': { body: fakeFileRules() },
    // Quick search in the command palette (WP-027): nothing found unless a test says otherwise.
    'GET /api/v1/incidents/search': { body: { items: [], people: {} } },
    // Branding (WP-017): the default brand unless a test says otherwise.
    'GET /api/v1/public/branding': {
      body: {
        customised: false,
        primary_colour: '#7e40d1',
        gradient: ['#6060de', '#951ab6'],
        logos: {},
      },
    },
    'GET /api/v1/organization/branding': { body: fakeBranding() },
    // Availability switch in the header (WP-029): available unless a test says otherwise.
    'GET /api/v1/automation/availability': { body: [] },
    'GET /api/v1/automation/loop-stops': { body: [] },
    // Notifications (WP-023): an empty centre and default preferences unless a test says otherwise.
    'GET /api/v1/notifications': { body: { items: [], next_cursor: null, unread: 0 } },
    'GET /api/v1/notifications/preferences': {
      body: { choices: [], do_not_disturb: false, version: 0 },
    },
    'GET /api/v1/notifications/status': { body: { mail_configured: true, waiting: 0 } },
    // The reply composer (QA6-INC-01): outgoing mail set up unless a test says otherwise.
    'GET /api/v1/notifications/mail-status': {
      body: { mail_configured: true, waiting: 0, who_can_fix: [] },
    },
    // Instance settings (WP-042): the built-in defaults; the header offers every language.
    'GET /api/v1/organization/settings': {
      body: {
        time_zone: null,
        week_start: 'monday',
        date_format: 'dd/mm/yyyy',
        time_format: '24h',
        country: null,
        fiscal_year_start_month: 1,
        contact_email: null,
        contact_phone: null,
        base_currency: 'USD',
        languages: ['en', 'ar', 'ur'],
        default_language: 'en',
        version: 1,
      },
      headers: { ETag: '"1"' },
    },
    // The approvals drawer in the header (WP-030 s2): nothing waits unless a test says otherwise.
    'GET /api/v1/service-requests/my-approvals': { body: { items: [], people: {} } },
    // Your reminders in the header (WP-046a S2): none unless a test says otherwise.
    'GET /api/v1/my-reminders': { body: [] },
    ...routes,
    ...listsByPost(routes),
  });
}

export const ME_PATH = ME;

/**
 * The calls to a list: a work-item list's `POST <path>/list` calls, each with a URL rebuilt from its body
 * (`view`, `tag`, `filter`, `sort`, `cursor`, `limit`), so a test reads it as it read the GET.
 */
export function listCalls(
  fake: { find: (method: string, path: string) => RecordedCall[] },
  path: string,
): RecordedCall[] {
  const posted = fake.find('POST', `${path}/list`);
  // Lists without a POST form (assets ...) are read as they are.
  if (posted.length === 0) return fake.find('GET', path);
  return posted.map((call) => {
    const body = (call.body ?? {}) as {
      filter?: unknown;
      sort?: string | null;
      cursor?: string | null;
      limit?: number;
      include_total?: boolean;
      params?: Record<string, string[]>;
    };
    const url = new URL(call.url.toString().replace(/\/list(\?|$)/, '$1'));
    for (const [name, values] of Object.entries(body.params ?? {})) {
      for (const value of values) url.searchParams.append(name, value);
    }
    if (body.filter !== undefined && body.filter !== null) {
      url.searchParams.set('filter', JSON.stringify(body.filter));
    }
    if (body.sort !== undefined && body.sort !== null) url.searchParams.set('sort', body.sort);
    if (body.cursor !== undefined && body.cursor !== null) {
      url.searchParams.set('cursor', body.cursor);
    }
    if (body.limit !== undefined) url.searchParams.set('limit', String(body.limit));
    if (body.include_total === true) url.searchParams.set('include_total', 'true');
    return { ...call, url };
  });
}
