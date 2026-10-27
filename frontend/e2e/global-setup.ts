import { randomBytes } from 'node:crypto';

import {
  fixtures,
  keycloakAdmin,
  keycloakUserId,
  tenantAddressCallbacks,
  USERS,
  type E2eUser,
} from './stack';

/**
 * Before the suite: make sure the e2e users exist in Keycloak (Demo Company, with their roles),
 * give each a fresh random password for this run (never stored), and create the scroll-test
 * user rows. Only records with reserved e2e names are created or changed.
 */
export default async function globalSetup(): Promise<void> {
  const admin = await keycloakAdmin();
  const orgs = (await (await admin('/organizations?search=Demo%20Company&exact=true')).json()) as {
    id: string;
  }[];
  const org = orgs[0];
  if (org === undefined)
    throw new Error('Demo Company organization is missing (make dev-up imports it)');

  for (const key of Object.keys(USERS) as E2eUser[]) {
    const user = USERS[key];
    let id = await keycloakUserId(admin, user.email);
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
      id = await keycloakUserId(admin, user.email);
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
  // The tenant-address journey (WP-017) signs in on demo.localhost and other.localhost.
  await tenantAddressCallbacks(admin, 'add');
  fixtures('create');
}
