import { expect, test, type Page } from '@playwright/test';

import { actionLink, mailTo, privateWindow, setPassword } from '../mail';
import { keycloakAdmin, keycloakUserId, passwordOf, PORTAL_URL, USERS } from '../stack';
import { nextStep, totp } from '../totp';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-039 session 3, against the Compose stack's Keycloak and mail catcher:
 * - REQ-SEC-017 AC1: an admin sets the password policy, the MFA policy and the session timeouts
 *   using only SupportX screens (single sign-on: sso.spec.ts); everything is put back after;
 * - REQ-SEC-022, 024, 025: with MFA required and no grace period, a person's next sign-in makes
 *   them set up an authenticator app and recovery codes first; an old code is refused; a
 *   recovery code works once; an admin's reset makes them set it up again; an admin cannot reset
 *   their own;
 * - REQ-SEC-028: My account opens without any code;
 * - REQ-SEC-029 AC2: what was typed into a new incident is back after the session ended.
 */
const RUN = Date.now().toString(36);
const PERSON = { first: 'Mfa', last: `Person ${RUN}`, email: `mfa.${RUN}@demo.test` };
const PASSWORD = `Mfa-${RUN}-Harbour-4`;

interface Me {
  csrf_token: string;
  user: { id: string };
}

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

interface Settings {
  version: number;
  password_min_length: number;
  mfa_grace_days: number;
  portal_idle_seconds: number;
}

async function settings(page: Page): Promise<Settings> {
  return (await (await call(page, 'GET', '/identity/settings')).json()) as Settings;
}

async function requesterRole(
  page: Page,
): Promise<{ role_id: string; version: number; mode: string }> {
  const found = (await (await call(page, 'GET', '/identity/mfa')).json()) as {
    roles: { key: string | null; role_id: string; version: number; mode: string }[];
  };
  const role = found.roles.find((r) => r.key === 'requester');
  if (role === undefined) throw new Error('no requester role');
  return role;
}

/** Sign in at Keycloak's page (identity-first: the address, then the password). */
async function signInAtKeycloak(page: Page, email: string, password: string): Promise<void> {
  await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
  await page.locator('#username').fill(email);
  await page.locator('#kc-login').click();
  await page.locator('#password').fill(password);
  await page.locator('#kc-login').click();
}

test('every sign-in setting is set in SupportX screens (REQ-SEC-017)', async ({ page }) => {
  test.skip(
    process.env.SUPPORTX_E2E_KEYCLOAK_URL !== undefined,
    'needs the Compose stack (k3d: covered by the API tests)',
  );
  await signInAs(page, 'admin', '/admin/security');
  const before = await settings(page);
  const role = await requesterRole(page);
  try {
    await expectAccessible(page, 'Admin › Sign-in and security, every card');
    // Password policy.
    await page.getByTestId('security-password_min_length').fill('14');
    await page.getByTestId('security-password-save').click();
    await expect(page.getByText('Password policy saved.', { exact: false })).toBeVisible();
    // Two-step sign-in: required for requesters, a 3-day grace period.
    const mfa = page.getByTestId('security-mfa');
    await mfa.getByTestId('security-mfa-mode-requester').getByText('Required').click();
    await expect(
      mfa.getByTestId('security-mfa-mode-requester').locator('.ant-segmented-item-selected'),
    ).toHaveText('Required');
    await mfa.getByTestId('security-mfa-grace').fill('3');
    await mfa.getByTestId('security-mfa-grace-save').click();
    // Each card saves with the settings version (D-103): the next card waits for this save.
    await expect(page.getByText('Saved.', { exact: true })).toBeVisible();
    // Sessions: the portal signs out after 20 idle minutes.
    await page.getByTestId('security-portal-idle').fill('20');
    await page.getByTestId('security-sessions-save').click();
    await expect(page.getByText('Sign-in settings saved.')).toBeVisible();
    await expect
      .poll(async () => {
        const now = await settings(page);
        return [now.password_min_length, now.mfa_grace_days, now.portal_idle_seconds];
      })
      .toEqual([14, 3, 1200]);
    expect((await requesterRole(page)).mode).toBe('required');
  } finally {
    const now = await settings(page);
    await call(
      page,
      'PUT',
      '/identity/settings',
      {
        password_min_length: before.password_min_length,
        mfa_grace_days: before.mfa_grace_days,
        portal_idle_seconds: before.portal_idle_seconds,
      },
      now.version,
    );
    const current = await requesterRole(page);
    await call(
      page,
      'PUT',
      `/identity/mfa/roles/${role.role_id}`,
      { mode: role.mode },
      current.version,
    );
  }
});

test('required MFA: set up at the next sign-in, codes and recovery, reset by an admin', async ({
  browser,
  page,
}) => {
  test.skip(
    process.env.SUPPORTX_E2E_KEYCLOAK_URL !== undefined,
    'needs the Compose mail catcher (k3d: covered by the API tests)',
  );
  test.setTimeout(240_000);
  await signInAs(page, 'admin', '/admin/security');
  const before = await settings(page);
  const role = await requesterRole(page);
  try {
    // A requester with a password (invited, as a real one would be).
    const made = await call(page, 'POST', '/users', {
      first_name: PERSON.first,
      last_name: PERSON.last,
      email: PERSON.email,
    });
    expect(made.status(), await made.text()).toBe(201);
    const personId = ((await made.json()) as { id: string }).id;
    const invitedAt = Date.now() - 1000;
    expect(
      (await call(page, 'POST', '/identity/invitations', { user_id: personId })).status(),
    ).toBe(201);
    const invited = await privateWindow(browser);
    await invited.goto(actionLink((await mailTo(PERSON.email, invitedAt)).html));
    const proceed = invited.getByRole('link', { name: /proceed/i });
    if (await proceed.isVisible()) await proceed.click();
    await setPassword(invited, PASSWORD);
    await expect(invited.locator('#password-new')).toHaveCount(0);
    await invited.context().close();

    // MFA required for requesters, no grace: the next sign-in sets it up first.
    await call(page, 'PUT', '/identity/settings', { mfa_grace_days: 0 }, before.version);
    await call(
      page,
      'PUT',
      `/identity/mfa/roles/${role.role_id}`,
      { mode: 'required' },
      role.version,
    );

    const person = await privateWindow(browser);
    await person.goto(PORTAL_URL);
    await signInAtKeycloak(person, PERSON.email, PASSWORD);
    // The first sign-in creates the person's SupportX record; MFA then turns out to be due, so
    // SupportX sends the browser round once more and Keycloak asks for the app before anything.
    await expect(person.locator('#totp')).toBeVisible({ timeout: 30_000 });
    const secret = await person.locator('#totpSecret').inputValue();
    await person.locator('#totp').fill('000000');
    await person.locator('#saveTOTPBtn').click();
    await expect(person.getByText(/invalid/i).first()).toBeVisible(); // AC2: refused, try again
    await person.locator('#totp').fill(totp(secret));
    await person.locator('#saveTOTPBtn').click();
    // Recovery codes come next.
    await expect(person.locator('#kcRecoveryCodesConfirmationCheck')).toBeVisible();
    const codes = await person.evaluate(() =>
      [...document.querySelectorAll('li')]
        .map((li) => li.innerText.trim())
        .filter((text) => /^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(text)),
    );
    expect(codes.length).toBeGreaterThan(1);
    await person.locator('#kcRecoveryCodesConfirmationCheck').check();
    await person.locator('#saveRecoveryAuthnCodesBtn').click();
    await expect(person.getByTestId('user-menu')).toBeVisible({ timeout: 30_000 });
    // My account opens without any code and shows MFA on.
    await person.goto(`${PORTAL_URL}/account`);
    await expect(person.getByTestId('account-mfa-state')).toHaveText('On');
    await person.context().close();

    // The next sign-in asks for a code: an old one is refused, the current one works.
    const again = await privateWindow(browser);
    await again.goto(PORTAL_URL);
    await signInAtKeycloak(again, PERSON.email, PASSWORD);
    await again.locator('#otp').fill(totp(secret, Date.now() - 120_000));
    await again.locator('#kc-login').click();
    await expect(again.getByText(/invalid authenticator code/i)).toBeVisible();
    await nextStep(); // the enrolment just used this step's code: a used code is refused
    await again.locator('#otp').fill(totp(secret));
    await again.locator('#kc-login').click();
    await expect(again.getByTestId('user-menu')).toBeVisible({ timeout: 30_000 });
    await again.context().close();

    // A recovery code instead of the app, once.
    for (const round of [1, 2]) {
      const lost = await privateWindow(browser);
      await lost.goto(PORTAL_URL);
      await signInAtKeycloak(lost, PERSON.email, PASSWORD);
      await lost.locator('#try-another-way').click();
      await lost
        .getByText(/recovery authentication code/i)
        .first()
        .click();
      await lost.locator('#recoveryCodeInput').fill(codes[0] ?? '');
      await lost.locator('#kc-login').click();
      if (round === 1) await expect(lost.getByTestId('user-menu')).toBeVisible({ timeout: 30_000 });
      else await expect(lost.getByText(/invalid recovery authentication code/i)).toBeVisible();
      await lost.context().close();
    }

    // An admin resets it (never their own): set up again at the next sign-in.
    await page.goto('/admin/users');
    await page.getByTestId('users-search').fill(PERSON.email);
    await page.getByTestId('users-table').getByText(`${PERSON.first} ${PERSON.last}`).click();
    const actions = page.getByTestId('person-drawer').getByTestId('person-sign-in-actions');
    const resetAt = Date.now() - 1000;
    await actions.getByTestId('person-reset-mfa').click();
    await page
      .locator('.ant-popconfirm')
      .getByRole('button', { name: 'Reset two-step sign-in' })
      .click();
    await expect(page.getByText('sets up two-step sign-in again', { exact: false })).toBeVisible();
    expect((await mailTo(PERSON.email, resetAt)).summary.Subject).toBe(
      'Your two-step sign-in was reset',
    );
    const reset = await privateWindow(browser);
    await reset.goto(PORTAL_URL);
    await signInAtKeycloak(reset, PERSON.email, PASSWORD);
    await expect(reset.locator('#totp')).toBeVisible({ timeout: 30_000 });
    await reset.context().close();
  } finally {
    const now = await settings(page);
    await call(
      page,
      'PUT',
      '/identity/settings',
      { mfa_grace_days: before.mfa_grace_days },
      now.version,
    );
    const current = await requesterRole(page);
    await call(
      page,
      'PUT',
      `/identity/mfa/roles/${role.role_id}`,
      { mode: role.mode },
      current.version,
    );
    const admin = await keycloakAdmin();
    const id = await keycloakUserId(admin, PERSON.email);
    if (id !== null) await admin(`/users/${id}`, { method: 'DELETE' });
  }
});

test('an admin is never offered a reset of their own MFA', async ({ page }) => {
  await signInAs(page, 'admin', '/admin/users');
  await page.getByTestId('users-search').fill(USERS.admin.email);
  await page.getByTestId('users-table').getByText(USERS.admin.email).click();
  await expect(page.getByTestId('person-sign-in-actions')).toBeVisible();
  await expect(page.getByTestId('person-reset-mfa')).toHaveCount(0);
});

test('a new incident keeps what was typed through the end of the session (REQ-SEC-029 AC2)', async ({
  page,
}) => {
  await signInAs(page, 'admin', '/incidents/new');
  const subject = `Kept ${RUN}`;
  await page.getByTestId('inc-subject').fill(subject);
  await page.waitForTimeout(800); // the draft is written shortly after typing
  // The session ends on the server (a timeout would do the same); the drafts stay in this tab.
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
  await page.request.post('/api/v1/auth/logout', { headers: { 'X-CSRF-Token': me.csrf_token } });
  await page.reload();
  await signInAtKeycloak(page, USERS.admin.email, passwordOf('admin'));
  await expect(page.getByTestId('inc-draft-restored')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('inc-subject')).toHaveValue(subject);
  await page.getByTestId('inc-draft-start-empty').click(); // leave nothing behind
});
