import { randomBytes } from 'node:crypto';

import { fixtures, stackEnv, USERS, type E2eUser } from './stack';

/**
 * Before the suite: make sure the e2e users exist in Keycloak (Demo Company, with their roles),
 * give each a fresh random password for this run (never stored), and create the scroll-test
 * user rows. Only records with reserved e2e names are created or changed.
 */
export default async function globalSetup(): Promise<void> {
  const env = stackEnv();
  const base = `http://localhost:${env.KEYCLOAK_PORT ?? '28080'}`;
  const token = await adminToken(base, env);
  const admin = async (path: string, init: RequestInit = {}) => {
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
  const orgs = (await (await admin('/organizations?search=Demo%20Company&exact=true')).json()) as {
    id: string;
  }[];
  const org = orgs[0];
  if (org === undefined)
    throw new Error('Demo Company organization is missing (make dev-up imports it)');

  for (const key of Object.keys(USERS) as E2eUser[]) {
    const user = USERS[key];
    let id = await userId(admin, user.email);
    if (id === null) {
      await admin('/users', {
        method: 'POST',
        body: JSON.stringify({
          username: user.email,
          email: user.email,
          emailVerified: true,
          enabled: true,
          firstName: user.first,
          lastName: user.last,
          attributes: { locale: ['en'] },
        }),
      });
      id = await userId(admin, user.email);
    }
    if (id === null) throw new Error(`could not create ${user.email}`);
    const roles = await Promise.all(
      user.roles.map(async (role) => (await (await admin(`/roles/${role}`)).json()) as unknown),
    );
    await admin(`/users/${id}/role-mappings/realm`, {
      method: 'POST',
      body: JSON.stringify(roles),
    });
    await admin(`/organizations/${org.id}/members`, { method: 'POST', body: JSON.stringify(id) });
    // 'Aa1!' satisfies the realm's character classes; the hex part makes it unique per run.
    const password = `${randomBytes(12).toString('hex')}Aa1!`;
    await admin(`/users/${id}/reset-password`, {
      method: 'PUT',
      body: JSON.stringify({ type: 'password', value: password, temporary: false }),
    });
    process.env[`SUPPORTX_E2E_PASSWORD_${key.toUpperCase()}`] = password;
  }
  fixtures('create');
}

async function adminToken(base: string, env: Record<string, string>): Promise<string> {
  const response = await fetch(`${base}/realms/master/protocol/openid-connect/token`, {
    method: 'POST',
    body: new URLSearchParams({
      grant_type: 'password',
      client_id: 'admin-cli',
      username: env.KEYCLOAK_ADMIN_USER ?? 'admin',
      password: env.KEYCLOAK_ADMIN_PASSWORD ?? '',
    }),
  });
  if (!response.ok) throw new Error(`Keycloak admin login failed: ${String(response.status)}`);
  return ((await response.json()) as { access_token: string }).access_token;
}

async function userId(
  admin: (path: string) => Promise<Response>,
  email: string,
): Promise<string | null> {
  const found = (await (
    await admin(`/users?email=${encodeURIComponent(email)}&exact=true`)
  ).json()) as { id: string }[];
  return found[0]?.id ?? null;
}
