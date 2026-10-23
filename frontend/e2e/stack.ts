/**
 * The dev stack the suite runs against: Keycloak admin access (from deploy/compose/.env, written
 * by `make dev-init`), the backend dev tools, and the users the suite works with.
 */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO = resolve(HERE, '../..');

export function stackEnv(): Record<string, string> {
  const text = readFileSync(resolve(REPO, 'deploy/compose/.env'), 'utf8');
  return Object.fromEntries(
    text
      .split('\n')
      .filter((line) => /^[A-Z_]+=/.test(line))
      .map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)]),
  );
}

/** `make dev-subscription` (documented reset tool, WP-009): change a dev tenant's plan. */
export function devSubscription(tenant: 'demo' | 'other', args: string): string {
  return execFileSync('make', ['-s', 'dev-subscription', `TENANT=${tenant}`, `ARGS=${args}`], {
    cwd: REPO,
    encoding: 'utf8',
  });
}

/** Backend e2e fixtures (tooling/e2e_fixtures.py): `create` or `delete` the scroll-test users. */
export function fixtures(action: 'create' | 'delete'): string {
  return execFileSync('uv', ['run', 'python', '-m', 'tooling.e2e_fixtures', action], {
    cwd: resolve(REPO, 'backend'),
    encoding: 'utf8',
  });
}

/**
 * Users of the suite. The two e2e users are created by global-setup (own test records, never a
 * seeded user's data); the seeded users are only signed in, never edited.
 */
export const USERS = {
  tech: { email: 'e2e.tech@demo.test', first: 'Erin', last: 'E2E Tech', roles: ['technician'] },
  limited: {
    email: 'e2e.limited@demo.test',
    first: 'Lina',
    last: 'E2E Limited',
    roles: ['requester'],
  },
  admin: {
    email: 'e2e.admin@demo.test',
    first: 'Adel',
    last: 'E2E Admin',
    roles: ['tenant_admin', 'technician'],
  },
} as const;
export type E2eUser = keyof typeof USERS;

/** Seeded users (docs/dev-setup.md); passwords are the documented dev ones. */
export const SEEDED = {
  arabic: { email: 'user@demo.test', password: 'User-Demo-2026!' },
  other: { email: 'other@other.test', password: 'Other-Corp-2026!' },
  tech: { email: 'tech@demo.test', password: 'Tech-Demo-2026!' },
} as const;

export function passwordOf(user: E2eUser): string {
  const value = process.env[`SUPPORTX_E2E_PASSWORD_${user.toUpperCase()}`];
  if (value === undefined) throw new Error('global-setup did not run');
  return value;
}

export type KeycloakAdmin = (path: string, init?: RequestInit) => Promise<Response>;

/** Keycloak admin API on the dev realm (dev credentials from deploy/compose/.env). */
export async function keycloakAdmin(): Promise<KeycloakAdmin> {
  const env = stackEnv();
  const base = `http://localhost:${env.KEYCLOAK_PORT ?? '28080'}`;
  const tokenResponse = await fetch(`${base}/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    body: new URLSearchParams({
      grant_type: 'password',
      client_id: 'admin-cli',
      username: env.KEYCLOAK_ADMIN_USER ?? 'admin',
      password: env.KEYCLOAK_ADMIN_PASSWORD ?? '',
    }),
  });
  if (!tokenResponse.ok) {
    throw new Error(`Keycloak admin login failed: ${String(tokenResponse.status)}`);
  }
  const token = ((await tokenResponse.json()) as { access_token: string }).access_token;
  return async (path, init = {}) => {
    const response = await fetch(`${base}/admin/realms/supportx${path}`, {
      ...init,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    });
    if (!response.ok && response.status !== 409) {
      throw new Error(
        `Keycloak ${init.method ?? 'GET'} ${path}: ${String(response.status)} ${await response.text()}`,
      );
    }
    return response;
  };
}

export async function keycloakUserId(admin: KeycloakAdmin, email: string): Promise<string | null> {
  const found = (await (
    await admin(`/users?email=${encodeURIComponent(email)}&exact=true`)
  ).json()) as { id: string }[];
  return found[0]?.id ?? null;
}

/** Change a suite user's last name in Keycloak (synced to SupportX at their next login). */
export async function renameSuiteUser(user: E2eUser, lastName: string): Promise<void> {
  const admin = await keycloakAdmin();
  const id = await keycloakUserId(admin, USERS[user].email);
  if (id === null) throw new Error(`${USERS[user].email} is missing`);
  await admin(`/users/${id}`, { method: 'PUT', body: JSON.stringify({ lastName }) });
}
