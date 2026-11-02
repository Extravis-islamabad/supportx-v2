import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { expect, test, type Browser, type Page } from '@playwright/test';

import { CONSOLE_URL, passwordOf, REPO, SEEDED, USERS } from '../stack';
import { expectAccessible } from './helpers';

/**
 * WP-017 end to end (REQ-ADM-055, REQ-PRT-016, REQ-SEC-003, REQ-SEC-004), on two tenant addresses:
 * demo.<console host> (Demo Company) and other.<console host> (Other Company), e.g.
 * demo.localhost:5173 on the dev stack, both served by the console's
 * dev server. An admin brands Demo Company through the API (a logo and a colour); then:
 * - its address goes straight to its own, branded sign-in page, accessible in English and Arabic;
 * - signed in, the console shows the logo and favicon; a second save reaches an open console live;
 * - the other address keeps the default brand, and a Demo Company person gets no access there.
 *
 * Demo Company's branding is put back to the default at the end (the suite's own change).
 */
/** A tenant's own address beside the console's: demo.localhost:5173 on the dev stack. */
function tenantAddress(slug: string): string {
  const url = new URL(CONSOLE_URL);
  url.hostname = `${slug}.${url.hostname}`;
  return url.origin;
}
const DEMO = tenantAddress('demo');
const OTHER = tenantAddress('other');
const BRAND = '#0b5394'; // white text 7.6:1
const LOGO = resolve(REPO, 'docs/brand/supportx-icon.png');

async function api(page: Page, method: string, path: string, data?: unknown, headers = {}) {
  const me = (await (await page.request.get(`${DEMO}/api/v1/auth/me`)).json()) as {
    csrf_token: string;
  };
  return page.request.fetch(`${DEMO}/api/v1${path}`, {
    method,
    data,
    headers: { 'X-CSRF-Token': me.csrf_token, ...headers },
  });
}

async function signInOn(page: Page, origin: string, email: string, password: string) {
  await page.goto(`${origin}/`);
  await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
  await page.locator('#username').fill(email);
  await page.locator('#kc-login').click();
  await page.locator('#password').fill(password);
  await page.locator('#kc-login').click();
}

async function primaryButtonColour(page: Page): Promise<string> {
  return page.locator('#kc-login').evaluate((node) => getComputedStyle(node).backgroundColor);
}

async function save(page: Page, body: Record<string, unknown>) {
  const current = await api(page, 'GET', '/organization/branding/settings');
  expect(current.status(), await current.text()).toBe(200);
  const version = ((await current.json()) as { version: number }).version;
  const saved = await api(page, 'PUT', '/organization/branding/settings', body, {
    'If-Match': `"${String(version)}"`,
  });
  expect(saved.status(), await saved.text()).toBe(200);
  return (await saved.json()) as { logos: { full: string | null; favicon: string | null } };
}

async function freshContext(browser: Browser, locale?: string) {
  const context = await browser.newContext(locale === undefined ? {} : { locale });
  return { context, page: await context.newPage() };
}

test('two tenants on two addresses: own sign-in page, own brand live everywhere, no access across', async ({
  browser,
  page,
}) => {
  test.setTimeout(180_000);
  // Tenant addresses are configured when the address's sign-in asks for its organization.
  // On the cluster an address nobody answers means tenant addresses are not set up there; on the
  // dev stack the probe must answer, so a failure there fails the test (lane B review, #125).
  const onCluster = process.env.SUPPORTX_E2E_KEYCLOAK_URL !== undefined;
  const asked = await page.request
    .get(`${DEMO}/api/v1/auth/login`, { maxRedirects: 0 })
    .then((probe) => {
      // Off the cluster the sign-in always redirects: an error page (5xx) must fail, not skip.
      if (!onCluster) expect(probe.status(), 'the sign-in redirects').toBe(302);
      return probe.headers().location ?? '';
    })
    .catch((error: unknown) => {
      if (onCluster) return '';
      throw error;
    });
  test.skip(
    !asked.includes('organization%3Ademo'),
    'tenant addresses are not configured on this stack (SUPPORTX_TENANT_BASE_DOMAIN)',
  );

  await signInOn(page, DEMO, USERS.admin.email, passwordOf('admin'));
  await expect(page.getByTestId('user-menu')).toBeVisible();
  expect(new URL(page.url()).host).toBe(new URL(DEMO).host); // the session stays on the address
  try {
    // A brand-manager upload, scanned, then saved with a colour and a product name.
    const uploaded = await page.request.post(
      `${DEMO}/api/v1/files?owner_type=branding&owner_id=${await tenantId(page)}&name=logo.png`,
      {
        data: readFileSync(LOGO),
        headers: {
          'X-CSRF-Token': await csrf(page),
          'Idempotency-Key': crypto.randomUUID(),
          'Content-Type': 'image/png',
        },
      },
    );
    expect(uploaded.status(), await uploaded.text()).toBe(201);
    const fileId = ((await uploaded.json()) as { id: string }).id;
    await expect
      .poll(
        async () =>
          ((await (await api(page, 'GET', `/files/${fileId}`)).json()) as { state: string }).state,
        {
          timeout: 60_000,
        },
      )
      .toBe('clean');
    const saved = await save(page, {
      primary_colour: BRAND,
      logo_file_id: fileId,
      product_name: { en: 'Demo Desk' },
    });
    expect(saved.logos.full).toMatch(/\/api\/v1\/public\/branding\/[0-9a-f-]{36}\/logo\.png/);

    // The signed-in console shows the tenant's logo and favicon.
    await page.reload();
    await expect(page.getByTestId('brand-logo-full').first()).toHaveAttribute(
      'src',
      /\/public\/branding\/[0-9a-f-]{36}\/logo\.png/,
    );
    await expect(page.getByTestId('brand-logo-full').first()).toHaveAttribute('alt', 'Demo Desk');
    await expect(page.locator('link[rel="icon"]').first()).toHaveAttribute(
      'href',
      /\/public\/branding\/[0-9a-f-]{36}\/favicon\.ico/,
    );

    // Live (REQ-ADM-055 AC1): a second save reaches this open console without a reload.
    const watcher = await browser.newContext();
    const live = await watcher.newPage();
    await signInOn(live, DEMO, USERS.admin.email, passwordOf('admin'));
    await expect(live.getByTestId('user-menu')).toBeVisible();
    await save(page, {
      primary_colour: BRAND,
      logo_file_id: fileId,
      product_name: { en: 'Demo Help' },
    });
    await expect(live.getByTestId('brand-logo-full').first()).toHaveAttribute('alt', 'Demo Help');
    await watcher.close();

    // REQ-SEC-003/-004 AC1: the address goes straight to the tenant's own sign-in page.
    for (const locale of ['en', 'ar']) {
      const { context, page: login } = await freshContext(browser, locale);
      try {
        await login.goto(`${DEMO}/`);
        await expect(login).toHaveURL(/scope=[^&]*organization%3Ademo/);
        await expect(
          login.locator('link[href$="/login.css"][href*="/public/branding/"]'),
        ).toHaveCount(1);
        await expect.poll(() => primaryButtonColour(login)).toBe('rgb(11, 83, 148)');
        await expect
          .poll(() =>
            login
              .locator('#kc-header-wrapper')
              .evaluate((n) => getComputedStyle(n).backgroundImage),
          )
          .toMatch(/\/public\/branding\/[0-9a-f-]{36}\/logo\.png/);
        if (locale === 'ar') await expect(login.locator('html')).toHaveAttribute('dir', 'rtl');
        await expectAccessible(login, `Demo Company sign-in page (${locale})`);
      } finally {
        await context.close();
      }
    }

    // The other address keeps the default brand, and its own people sign in there.
    {
      const { context, page: other } = await freshContext(browser);
      try {
        await other.goto(`${OTHER}/`);
        await expect(other).toHaveURL(/scope=[^&]*organization%3Aother/);
        await expect.poll(() => primaryButtonColour(other)).toBe('rgb(126, 64, 209)');
        await signInOn(other, OTHER, SEEDED.other.email, SEEDED.other.password);
        await expect(other.getByTestId('user-menu')).toBeVisible();
        await expect(other.getByTestId('brand-logo-full').first()).not.toHaveAttribute(
          'src',
          /\/public\/branding\//,
        );
      } finally {
        await context.close();
      }
    }

    // REQ-SEC-004 AC2: a Demo Company person on Other Company's address gets no access.
    {
      const { context, page: across } = await freshContext(browser);
      try {
        await signInOn(across, OTHER, USERS.admin.email, passwordOf('admin'));
        await expect(across).toHaveURL((url) =>
          url.href.startsWith(`${OTHER}/?auth_error=no_organization`),
        );
        const me = await across.request.get(`${OTHER}/api/v1/auth/me`);
        expect(me.status()).toBe(401);
      } finally {
        await context.close();
      }
    }
  } finally {
    await save(page, {});
  }
});

async function csrf(page: Page): Promise<string> {
  return (
    (await (await page.request.get(`${DEMO}/api/v1/auth/me`)).json()) as { csrf_token: string }
  ).csrf_token;
}

async function tenantId(page: Page): Promise<string> {
  return (
    (await (await page.request.get(`${DEMO}/api/v1/auth/me`)).json()) as { tenant: { id: string } }
  ).tenant.id;
}
