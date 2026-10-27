/**
 * The stack the suite runs against: the Compose dev stack (Keycloak admin access from
 * deploy/compose/.env, written by `make dev-init`) or, with SUPPORTX_E2E_* set by
 * `make cluster-e2e`, the k3d cluster (WP-014). Also the backend dev tools and the suite's users.
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO = resolve(HERE, '../..');

/** The console: Playwright's baseURL (Vite dev server, or the cluster's public URL). */
export const CONSOLE_URL = process.env.SUPPORTX_CONSOLE_URL ?? 'http://localhost:5173';

/** The portal dev server (`pnpm --filter @supportx/portal dev`), or `<cluster>/portal`. */
export const PORTAL_URL = process.env.SUPPORTX_PORTAL_URL ?? 'http://localhost:5174';

/** The Compose stack's settings; empty when there is none (cluster runs in CI). */
export function stackEnv(): Record<string, string> {
  const path = resolve(REPO, 'deploy/compose/.env');
  if (!existsSync(path)) return {};
  const text = readFileSync(path, 'utf8');
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

/** The realtime gateway's token key, to forge tokens in the security tests (dev only). */
export function centrifugoTokenSecret(): string {
  return (
    process.env.SUPPORTX_E2E_CENTRIFUGO_TOKEN_SECRET ??
    stackEnv().CENTRIFUGO_TOKEN_HMAC_SECRET ??
    ''
  );
}

/** Keycloak admin API on the dev realm (Compose .env, or SUPPORTX_E2E_KEYCLOAK_* for k3d). */
export async function keycloakAdmin(): Promise<KeycloakAdmin> {
  const env = stackEnv();
  const base =
    process.env.SUPPORTX_E2E_KEYCLOAK_URL ?? `http://localhost:${env.KEYCLOAK_PORT ?? '28080'}`;
  const tokenResponse = await fetch(`${base}/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    body: new URLSearchParams({
      grant_type: 'password',
      client_id: 'admin-cli',
      username: process.env.SUPPORTX_E2E_KEYCLOAK_ADMIN_USER ?? env.KEYCLOAK_ADMIN_USER ?? 'admin',
      password:
        process.env.SUPPORTX_E2E_KEYCLOAK_ADMIN_PASSWORD ?? env.KEYCLOAK_ADMIN_PASSWORD ?? '',
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

/**
 * The dev tenants' own addresses (WP-017): demo.localhost and other.localhost, on the console and
 * portal ports. Their callbacks are registered on the clients for the run (`add`) and removed
 * after it (`remove`); realm files never carry UI origins.
 */
const TENANT_ADDRESS_CALLBACKS: Record<string, string[]> = {
  'supportx-console': ['demo', 'other'].map(
    (t) => `http://${t}.localhost:5173/api/v1/auth/callback`,
  ),
  'supportx-portal': ['demo', 'other'].map(
    (t) => `http://${t}.localhost:5174/api/v1/auth/callback`,
  ),
};

export async function tenantAddressCallbacks(
  admin: KeycloakAdmin,
  action: 'add' | 'remove',
): Promise<void> {
  for (const [clientId, uris] of Object.entries(TENANT_ADDRESS_CALLBACKS)) {
    const found = (await (await admin(`/clients?clientId=${clientId}`)).json()) as {
      id: string;
      redirectUris?: string[];
    }[];
    const client = found[0];
    if (client === undefined) continue;
    const current = client.redirectUris ?? [];
    const next =
      action === 'add'
        ? [...current, ...uris.filter((uri) => !current.includes(uri))]
        : current.filter((uri) => !uris.includes(uri));
    if (next.length === current.length && next.every((uri, i) => uri === current[i])) continue;
    const updated = await admin(`/clients/${client.id}`, {
      method: 'PUT',
      body: JSON.stringify({ ...client, redirectUris: next }),
    });
    if (!updated.ok) throw new Error(`could not update ${clientId}: ${String(updated.status)}`);
  }
}
