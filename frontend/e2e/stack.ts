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
