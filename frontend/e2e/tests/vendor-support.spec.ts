import { expect, test, type Page } from '@playwright/test';

import { mailTo, mailUnavailable, privateWindow, setPassword } from '../mail';
import { CONSOLE_URL, stackEnv } from '../stack';
import { totp } from '../totp';
import { FIRST_LOAD_AFTER_SIGN_IN_MS, signInAs } from './helpers';

// WP-057 S4c-3 (REQ-SEC-045, D-173, D-177): vendor support, end to end on the Compose stack.
// - The mailed link: its token never appears in a request URL or a Referer (lane B (1), the
//   coordinator's (2)); the temporary password is shown once; Keycloak makes the engineer
//   choose a password and set up a one-time code; the console says "Extravis support".
// - The grant's end with a record page open: the console stops and is signed out (lane B (6)).
// - The call-back path, through the admin's drawer: the password shown once stops working once
//   the engineer has chosen their own (the coordinator's condition 1).

const RUN = Date.now().toString(36);
const NEW_PASSWORD = `Support-${RUN}-Harbour-7`;

interface Me {
  csrf_token: string;
}

async function call(page: Page, method: string, path: string, body?: unknown) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
  return page.request.fetch(`/api/v1${path}`, {
    method,
    data: body,
    headers: { 'X-CSRF-Token': me.csrf_token, 'Idempotency-Key': crypto.randomUUID() },
  });
}

function mailpit(): string {
  return (
    process.env.SUPPORTX_E2E_MAIL_URL ??
    `http://localhost:${stackEnv().MAILPIT_WEB_PORT ?? '28025'}`
  );
}

/** The plain text of the link mail sent to `to` after `after`, and the link in it. */
async function supportLink(to: string, after: number): Promise<string> {
  const { summary } = await mailTo(to, after);
  const message = (await (await fetch(`${mailpit()}/api/v1/message/${summary.ID}`)).json()) as {
    Text: string;
  };
  const found = /(https?:\/\/\S*\/vendor-support\/start\S*#\S+)/.exec(message.Text);
  expect(found, 'the mail has the link').not.toBeNull();
  return found?.[1] ?? '';
}

/** Keycloak: the sign-in name, then the password (identity-first). */
async function signInAtKeycloak(page: Page, login: string, password: string): Promise<void> {
  await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
  await page.locator('#username').fill(login);
  await page.locator('#kc-login').click();
  await page.locator('#password').fill(password);
  await page.locator('#kc-login').click();
}

/**
 * The first sign-in's required actions: a new password and a one-time code (D-177), then the
 * recovery codes if offered. Keycloak orders them by the realm's priorities (a fresh realm asks for
 * the code first), so each is handled as it appears; both the password and the code are required.
 */
async function firstSignIn(page: Page): Promise<void> {
  const password = page.locator('#password-new');
  const code = page.locator('#totp');
  const codes = page.locator('#kcRecoveryCodesConfirmationCheck');
  const done = new Set<string>();
  for (let step = 0; step < 3; step += 1) {
    const timeout = done.size === 0 ? 30_000 : 10_000;
    const shown = await password
      .or(code)
      .or(codes)
      .first()
      .waitFor({ state: 'visible', timeout })
      .then(() => true)
      .catch(() => false);
    if (!shown) break;
    if (await password.isVisible()) {
      await setPassword(page, NEW_PASSWORD);
      done.add('password');
    } else if (await code.isVisible()) {
      const secret = await page.locator('#totpSecret').inputValue();
      await code.fill(totp(secret));
      await page.locator('#saveTOTPBtn').click();
      done.add('code');
    } else {
      await codes.check();
      await page.locator('#saveRecoveryAuthnCodesBtn').click();
      done.add('recovery');
    }
    await expect(password.or(code).or(codes).first())
      .toBeHidden({ timeout: 10_000 })
      .catch(() => undefined);
  }
  expect([...done].filter((d) => d !== 'recovery').sort()).toEqual(['code', 'password']);
}

test.describe('vendor support', () => {
  test.skip(
    process.env.SUPPORTX_E2E_KEYCLOAK_URL !== undefined,
    'needs the Compose stack (k3d: covered by the API tests)',
  );

  test('the mailed link: one POST, nothing in a URL, then Extravis support until the grant ends', async ({
    page,
    browser,
  }) => {
    const skip = mailUnavailable();
    test.skip(skip !== null, skip ?? '');
    const email = `e2e.${RUN}@extravis.com`;
    await signInAs(page, 'admin', '/admin/security');
    // A guard, not the fix: the page's live connection first, as the other live specs do. The
    // console itself now catches up on a channel's first subscribe (packages/realtime, §8.3).
    await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', {
      timeout: 8_000,
    });
    const asked = Date.now();
    const made = await call(page, 'POST', '/identity/vendor-support/grants', {
      engineer_name: `QA-2026-11-20 E2E Engineer ${RUN}`,
      engineer_email: email,
      reason: 'E2E: a workflow is stuck',
      access: 'view',
      unmask_personal: false,
      verification: 'email',
      hours: 2,
    });
    expect(made.status(), await made.text()).toBe(201);
    const grant = (await made.json()) as { id: string; one_time_password: string | null };
    expect(grant.one_time_password).toBeNull(); // with mail, no password exists until the link
    try {
      // The admin's list shows it, live and in words.
      await expect(page.getByTestId('vendor-support-card')).toContainText(
        `QA-2026-11-20 E2E Engineer ${RUN}`,
      );

      const link = await supportLink(email, asked);
      const token = link.split('#')[1] ?? '';
      expect(token.length).toBeGreaterThan(20);
      const engineer = await privateWindow(browser);
      const seen: string[] = [];
      engineer.on('request', (request) => {
        seen.push(request.url(), request.headers().referer ?? '');
      });
      await engineer.goto(link);
      await expect(engineer).toHaveURL(/\/vendor-support\/start(\?|$)/);
      expect(engineer.url()).not.toContain(token); // gone from the address bar
      await engineer.getByTestId('support-start-open').click();
      const password = await engineer.getByTestId('support-start-password').inputValue();
      const login = await engineer.locator('#support-start-login').inputValue();
      expect(password.length).toBeGreaterThan(11);
      expect(seen.every((entry) => !entry.includes(token))).toBe(true);
      // The same link again: spent, one message (lane B (5)).
      const again = await privateWindow(browser);
      await again.goto(link);
      await again.getByTestId('support-start-open').click();
      await expect(again.getByTestId('support-start-failed')).toBeVisible();
      await again.context().close();

      await engineer.getByTestId('support-start-sign-in').click();
      await signInAtKeycloak(engineer, login, password);
      await firstSignIn(engineer);
      await expect(engineer.getByTestId('support-banner')).toBeVisible({
        timeout: FIRST_LOAD_AFTER_SIGN_IN_MS,
      });
      await expect(engineer.getByTestId('support-banner')).toContainText('Extravis support');

      // A record page open when the grant ends: the console stops and signs out (lane B (6)).
      const admin = (await (await page.request.get('/api/v1/auth/me')).json()) as {
        user: { id: string };
      };
      const incident = await call(page, 'POST', '/incidents', {
        subject: `QA-2026-11-20 E2E vendor support ${RUN}`,
        requester_id: admin.user.id,
      });
      expect(incident.status(), await incident.text()).toBe(201);
      const { id } = (await incident.json()) as { id: string };
      await engineer.goto(`${CONSOLE_URL}/incidents/${id}`);
      await expect(engineer.getByTestId('support-banner')).toBeVisible();
      const ended = await call(page, 'POST', `/identity/vendor-support/grants/${grant.id}/revoke`);
      expect(ended.status(), await ended.text()).toBe(200);
      await expect(engineer.getByTestId('support-banner')).toHaveCount(0, { timeout: 30_000 });
      await expect(engineer.getByTestId('user-menu')).toHaveCount(0);
      await engineer.context().close();
    } finally {
      await call(page, 'POST', `/identity/vendor-support/grants/${grant.id}/revoke`);
    }
  });

  test('the call-back path: the password shown once stops working once replaced', async ({
    page,
    browser,
  }) => {
    await signInAs(page, 'admin', '/admin/security');
    await page.getByTestId('vendor-support-grant').click();
    const drawer = page.getByTestId('vendor-support-grant-drawer');
    await drawer.getByTestId('vendor-support-name').fill(`QA-2026-11-20 E2E Caller ${RUN}`);
    await drawer.getByTestId('vendor-support-email').fill(`e2e.call.${RUN}@extravis.com`);
    await drawer.getByTestId('vendor-support-reason').fill('E2E: a report is wrong');
    await drawer.getByText('I confirmed the engineer by calling Extravis back').click();
    await drawer.getByTestId('vendor-support-note').fill('Called the published number back');
    await drawer.getByRole('button', { name: 'Give access' }).click();
    const shown = page.getByTestId('vendor-support-password-text');
    await expect(shown).toBeVisible({ timeout: 15_000 });
    const temporary = await shown.inputValue();
    await page.getByTestId('vendor-support-password-done').click();
    await expect(page.getByTestId('vendor-support-password')).toHaveCount(0);
    expect(await page.content()).not.toContain(temporary); // shown once, kept nowhere

    const grants = (await (await call(page, 'GET', '/identity/vendor-support/grants')).json()) as {
      id: string;
      engineer_name: string;
    }[];
    const grant = grants.find((g) => g.engineer_name === `QA-2026-11-20 E2E Caller ${RUN}`);
    expect(grant).toBeDefined();
    try {
      const login = `sx-support-${(grant?.id ?? '').replaceAll('-', '')}`;
      const engineer = await privateWindow(browser);
      await engineer.goto(CONSOLE_URL);
      await signInAtKeycloak(engineer, login, temporary);
      await firstSignIn(engineer);
      await expect(engineer.getByTestId('support-banner')).toBeVisible({
        timeout: FIRST_LOAD_AFTER_SIGN_IN_MS,
      });
      await engineer.context().close();
      // The temporary password no longer signs in (the coordinator's condition 1).
      const later = await privateWindow(browser);
      await later.goto(CONSOLE_URL);
      await signInAtKeycloak(later, login, temporary);
      await expect(later.getByText(/invalid/i).first()).toBeVisible({ timeout: 15_000 });
      await later.context().close();
    } finally {
      if (grant !== undefined) {
        await call(page, 'POST', `/identity/vendor-support/grants/${grant.id}/revoke`);
      }
    }
  });
});
