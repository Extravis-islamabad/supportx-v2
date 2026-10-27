import { expect, test, type Browser, type Page } from '@playwright/test';

import { keycloakAdmin, keycloakUserId, stackEnv } from '../stack';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-039 (REQ-SEC-007, REQ-SEC-013, REQ-SEC-017): single sign-on set up in SupportX screens
 * only, against a SAML identity provider that is a realm of the dev Keycloak, made for this run:
 * - the admin adds it from its metadata address; it is saved in draft and cannot be switched on;
 * - the test sign-in runs in a private window (this browser is signed in as the admin), lands on
 *   a page that needs no session, and the admin's screen shows who signed in;
 * - switched on, a person of its email domain is sent straight to it and lands in Demo Company
 *   as a requester (created on first sign-in);
 * - the screen is axe clean in light, dark and high contrast.
 *
 * SAML because its answer travels through the browser: in Compose, Keycloak cannot call itself
 * on the address the browser uses, which an OpenID Connect provider here would need. OpenID
 * Connect is covered by the API tests and was checked by hand against a real provider.
 * Everything made here (the realm, the set-up, the Keycloak user) is removed at the end.
 */
const RUN = Date.now().toString(36);
const REALM = `e2e-saml-${RUN}`;
const DOMAIN = `saml-${RUN}.test`;
const PERSON = { email: `sam@${DOMAIN}`, password: 'Sam-Saml-2026!' };

function keycloakBase(): string {
  return `http://localhost:${stackEnv().KEYCLOAK_PORT ?? '28080'}`;
}

/** The master realm's admin API (to make and remove the provider realm). */
async function masterAdmin(): Promise<(path: string, init?: RequestInit) => Promise<Response>> {
  const env = stackEnv();
  const token = (await (
    await fetch(`${keycloakBase()}/realms/master/protocol/openid-connect/token`, {
      method: 'POST',
      body: new URLSearchParams({
        grant_type: 'password',
        client_id: 'admin-cli',
        username: env.KEYCLOAK_ADMIN_USER ?? 'admin',
        password: env.KEYCLOAK_ADMIN_PASSWORD ?? '',
      }),
    })
  ).json()) as { access_token: string };
  return (path, init = {}) =>
    fetch(`${keycloakBase()}/admin${path}`, {
      ...init,
      headers: new Headers([
        ['Authorization', `Bearer ${token.access_token}`],
        ['Content-Type', 'application/json'],
        ...new Headers(init.headers).entries(),
      ]),
    });
}

async function makeProviderRealm(): Promise<void> {
  const admin = await masterAdmin();
  const supportx = `${keycloakBase()}/realms/supportx`;
  const attribute = (name: string, property: string) => ({
    name,
    protocol: 'saml',
    protocolMapper: 'saml-user-property-mapper',
    config: {
      'user.attribute': property,
      'attribute.name': `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/${name}`,
      'attribute.nameformat': 'URI Reference',
    },
  });
  const created = await admin('/realms', {
    method: 'POST',
    body: JSON.stringify({
      realm: REALM,
      enabled: true,
      users: [
        {
          username: PERSON.email,
          email: PERSON.email,
          firstName: 'Sam',
          lastName: 'Saml',
          enabled: true,
          emailVerified: true,
          credentials: [{ type: 'password', value: PERSON.password, temporary: false }],
        },
      ],
      clients: [
        {
          clientId: supportx, // the broker's service provider entity ID
          protocol: 'saml',
          enabled: true,
          redirectUris: [`${supportx}/broker/*`],
          attributes: {
            saml_name_id_format: 'email',
            'saml.force.name.id.format': 'true',
            'saml.client.signature': 'false',
            'saml.server.signature': 'true',
            'saml.assertion.signature': 'true',
          },
          protocolMappers: [
            attribute('emailaddress', 'email'),
            attribute('givenname', 'firstName'),
            attribute('surname', 'lastName'),
          ],
        },
      ],
    }),
  });
  expect(created.status, await created.text()).toBe(201);
}

async function signInAtProvider(page: Page): Promise<void> {
  await expect(page).toHaveURL(new RegExp(`/realms/${REALM}/`));
  await page.locator('#username').fill(PERSON.email);
  await page.locator('#password').fill(PERSON.password);
  await page.locator('#kc-login').click();
}

async function privateWindow(browser: Browser): Promise<Page> {
  return (await browser.newContext()).newPage();
}

test('single sign-on: set up, tested in a private window, switched on, used', async ({
  browser,
  page,
}) => {
  test.skip(
    process.env.SUPPORTX_E2E_KEYCLOAK_URL !== undefined,
    'the provider realm lives in the Compose Keycloak (k3d: covered by the API tests)',
  );
  test.setTimeout(180_000);
  await makeProviderRealm();
  let providerId: string | null = null;
  try {
    await signInAs(page, 'admin', '/admin/security');
    await expect(page.getByTestId('admin-security')).toBeVisible();
    for (const theme of ['light', 'dark', 'high_contrast'] as const) {
      await page.evaluate((value) => {
        window.localStorage.setItem('supportx.theme_mode', value);
      }, theme);
      await page.reload();
      await expect(page.getByTestId('security-sso')).toBeVisible();
      await expectAccessible(page, `Admin › Sign-in and security (${theme})`);
    }
    await page.evaluate(() => {
      window.localStorage.setItem('supportx.theme_mode', 'light');
    });
    await page.reload();

    // Added from the provider's metadata address, sending its domain straight to it once on.
    await page.getByTestId('sso-add').click();
    const editor = page.getByTestId('sso-editor');
    await editor.getByTestId('sso-preset').getByText('SAML 2.0').click();
    await editor.getByTestId('sso-display_name').fill('E2E SAML');
    await editor.getByRole('combobox').fill(`${DOMAIN},`);
    await editor
      .getByTestId('sso-metadata_url')
      .fill(`${keycloakBase()}/realms/${REALM}/protocol/saml/descriptor`);
    await editor.getByTestId('sso-email_redirect').click();
    const [saved] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().endsWith('/identity/sso') && r.request().method() === 'POST',
      ),
      page.getByTestId('sso-save').click(),
    ]);
    expect(saved.status(), await saved.text()).toBe(201);
    providerId = ((await saved.json()) as { id: string }).id;
    const row = page.getByTestId('sso-E2E SAML');
    await expect(row.getByTestId('sso-state')).toHaveText('Draft');
    await expect(row.getByTestId('sso-switch')).toBeDisabled(); // test first

    // The test: a link for a private window; no session there, the result shows here.
    const [started] = await Promise.all([
      page.waitForResponse((r) => r.url().endsWith('/tests') && r.request().method() === 'POST'),
      row.getByTestId('sso-test').click(),
    ]);
    const { url } = (await started.json()) as { url: string };
    const dialog = page.getByTestId('sso-test-dialog');
    await expect(dialog.getByTestId('sso-test-link')).toBeVisible();
    await expectAccessible(page, 'SSO test dialog');
    const tester = await privateWindow(browser);
    await tester.goto(url);
    await signInAtProvider(tester);
    await expect(tester.getByTestId('sso-test-done')).toBeVisible();
    await expect(dialog.getByTestId('sso-test-passed')).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByText(PERSON.email)).toBeVisible();
    await dialog.getByRole('button', { name: 'Close' }).first().click();
    expect(
      ((await (await page.request.get('/api/v1/auth/me')).json()) as { user: { email: string } })
        .user.email,
    ).toBe('e2e.admin@demo.test'); // the admin's own session is untouched

    await row.getByTestId('sso-switch').click();
    await expect(row.getByTestId('sso-state')).toHaveText('On');

    // A person of the domain: sent straight to the provider, then into Demo Company.
    const person = await privateWindow(browser);
    await person.goto('/');
    await person.locator('#username').fill(PERSON.email);
    await person.locator('#kc-login').click();
    await signInAtProvider(person);
    await expect(person.getByTestId('user-menu')).toBeVisible({ timeout: 30_000 });
    const me = (await (await person.request.get('/api/v1/auth/me')).json()) as {
      user: { email: string; user_type: string };
      tenant: { name: string };
    };
    expect([me.user.email, me.user.user_type, me.tenant.name]).toEqual([
      PERSON.email,
      'requester',
      'Demo Company',
    ]);
  } finally {
    if (providerId !== null) {
      const csrf = (
        (await (await page.request.get('/api/v1/auth/me')).json()) as {
          csrf_token: string;
        }
      ).csrf_token;
      const current = await page.request.get(`/api/v1/identity/sso/${providerId}`);
      const version = ((await current.json()) as { version: number }).version;
      await page.request.delete(`/api/v1/identity/sso/${providerId}`, {
        headers: { 'X-CSRF-Token': csrf, 'If-Match': `"${String(version)}"` },
      });
    }
    const supportx = await keycloakAdmin();
    const personId = await keycloakUserId(supportx, PERSON.email);
    if (personId !== null) await supportx(`/users/${personId}`, { method: 'DELETE' });
    await (
      await masterAdmin()
    )(`/realms/${REALM}`, { method: 'DELETE' });
  }
});
