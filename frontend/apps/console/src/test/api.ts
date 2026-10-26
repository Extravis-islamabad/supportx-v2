import {
  fakeApi,
  fakeAuditStatus,
  fakeFileRules,
  fakeFileStatus,
  fakeEntitlements,
  fakeSession,
  fakeUser,
  type FakeRoute,
} from '@supportx/api-client/testing';
import type { MeResponse } from '@supportx/api-client';

export { fakeEntitlements, fakeSession, fakeUser, problem } from '@supportx/api-client/testing';

const ME = '/api/v1/users/01900000-0000-7000-8000-000000000101';

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
    ...routes,
  });
}

export const ME_PATH = ME;
