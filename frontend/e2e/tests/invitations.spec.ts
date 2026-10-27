import { expect, test, type Browser, type Page } from '@playwright/test';

import { keycloakAdmin, keycloakUserId, PORTAL_URL, stackEnv } from '../stack';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-039 session 2 (REQ-SEC-005, 006, 018..020, 035; D-099): invitations, the password policy
 * and "Forgot password?" end to end, against the Compose stack's Keycloak and mail catcher:
 * - an admin adds a person and invites them from their record; the e-mail reaches the mail
 *   catcher, branded, from the installation's sender, never naming the admin;
 * - in a private window the person opens the link: a breached password is refused with the
 *   reason, a good one is taken, and they sign in to the portal; the admin's invitations list
 *   shows the invitation accepted without a reload;
 * - the reset page needs no session, always answers the same, and its e-mail arrives;
 * - the new screens are axe clean.
 * The Keycloak account made here is removed at the end.
 */
const RUN = Date.now().toString(36);
const PERSON = { first: 'Ina', last: `Vitee ${RUN}`, email: `ina.${RUN}@demo.test` };
const BREACHED = 'John!20130605At1753'; // on the shipped list (SecLists), meets every other rule
const PASSWORD = `Ina-${RUN}-Lantern-7`;

function mailpit(): string {
  return `http://localhost:${stackEnv().MAILPIT_WEB_PORT ?? '28025'}`;
}

interface MailSummary {
  ID: string;
  Subject: string;
  From: { Address: string; Name: string };
}

/** The newest message to `to` whose subject matches, waiting for it to arrive. */
async function mailTo(to: string, after: number): Promise<{ summary: MailSummary; html: string }> {
  let found: MailSummary | undefined;
  await expect
    .poll(
      async () => {
        const response = await fetch(
          `${mailpit()}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`,
        );
        const body = (await response.json()) as { messages: (MailSummary & { Created: string })[] };
        found = body.messages.find((m) => Date.parse(m.Created) >= after);
        return found !== undefined;
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  const summary: MailSummary | undefined = found;
  if (summary === undefined) throw new Error(`no e-mail to ${to}`);
  const message = (await (await fetch(`${mailpit()}/api/v1/message/${summary.ID}`)).json()) as {
    HTML: string;
  };
  return { summary, html: message.HTML };
}

function actionLink(html: string): string {
  const match = /href="([^"]*login-actions\/action-token[^"]*)"/.exec(html);
  expect(match, 'the e-mail has the set-password link').not.toBeNull();
  return (match?.[1] ?? '').replaceAll('&amp;', '&');
}

async function privateWindow(browser: Browser): Promise<Page> {
  return (await browser.newContext()).newPage();
}

async function setPassword(page: Page, password: string): Promise<void> {
  await page.locator('#password-new').fill(password);
  await page.locator('#password-confirm').fill(password);
  await page.locator('input[type=submit], button[type=submit]').first().click();
}

test('an invited person sets a password that meets the policy and signs in', async ({
  browser,
  page,
}) => {
  test.skip(
    process.env.SUPPORTX_E2E_KEYCLOAK_URL !== undefined,
    'needs the Compose mail catcher (k3d: covered by the API tests)',
  );
  test.setTimeout(180_000);
  try {
    await signInAs(page, 'admin', '/admin/users');
    const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
      csrf_token: string;
    };
    const made = await page.request.post('/api/v1/users', {
      data: { first_name: PERSON.first, last_name: PERSON.last, email: PERSON.email },
      headers: { 'X-CSRF-Token': me.csrf_token, 'Idempotency-Key': crypto.randomUUID() },
    });
    expect(made.status(), await made.text()).toBe(201);

    // Invited from their record.
    await page.reload();
    await page.getByTestId('users-search').fill(PERSON.email);
    await page.getByTestId('users-table').getByText(`${PERSON.first} ${PERSON.last}`).click();
    const drawer = page.getByTestId('person-drawer');
    const actions = drawer.getByTestId('person-sign-in-actions');
    await expectAccessible(page, 'person drawer with sign-in actions');
    const sentAt = Date.now() - 1000;
    await actions.getByTestId('person-invite').click();
    await expect(page.getByText(`Invitation sent to ${PERSON.email}.`)).toBeVisible();
    await expect(actions.getByTestId('person-invite-again')).toBeVisible();

    // The e-mail: the installation's sender with the organisation's name, never the admin.
    const invitation = await mailTo(PERSON.email, sentAt);
    expect(invitation.summary.From.Address).toBe('support@supportx.localhost');
    expect(invitation.html).toContain('Demo Company');
    expect(invitation.html).not.toContain('e2e.admin@demo.test');

    // The admin watches the invitations list while the person accepts.
    await page.goto('/admin/security');
    const list = page.getByTestId('security-invitations-list');
    const row = list.locator('tr', { hasText: PERSON.email });
    await expect(row.getByTestId('invitation-status')).toHaveText('Waiting');
    await expectAccessible(
      page,
      'Admin › Sign-in and security with password policy and invitations',
    );

    const person = await privateWindow(browser);
    await person.goto(actionLink(invitation.html));
    const proceed = person.getByRole('link', { name: /proceed/i });
    if (await proceed.isVisible()) await proceed.click();
    await setPassword(person, BREACHED);
    await expect(
      person.getByText('This password is too common or has appeared in a data breach.', {
        exact: false,
      }),
    ).toBeVisible();
    await setPassword(person, PASSWORD);
    await expect(person.locator('#password-new')).toHaveCount(0);

    // Setting the password left no session: the person signs in to the portal like anyone.
    await person.goto(PORTAL_URL);
    await expect(person).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
    await person.locator('#username').fill(PERSON.email);
    await person.locator('#kc-login').click();
    await person.locator('#password').fill(PASSWORD);
    await person.locator('#kc-login').click();
    await expect(person.getByTestId('user-menu')).toBeVisible({ timeout: 30_000 });
    await expect(row.getByTestId('invitation-status')).toHaveText('Accepted', { timeout: 15_000 });

    // Forgot password: no session, the same answer, and the e-mail arrives.
    const stranger = await privateWindow(browser);
    await stranger.goto(`${PORTAL_URL}/password-reset`);
    await expect(stranger.getByTestId('password-reset')).toBeVisible();
    await expectAccessible(stranger, 'password reset page');
    const askedAt = Date.now() - 1000;
    await stranger.getByTestId('reset-email').fill(PERSON.email);
    await stranger.getByTestId('reset-send').click();
    await expect(stranger.getByTestId('reset-sent')).toContainText(PERSON.email);
    const reset = await mailTo(PERSON.email, askedAt);
    expect(actionLink(reset.html)).toContain('action-token');
    // An address nobody has gets the very same answer.
    await stranger.goto(`${PORTAL_URL}/password-reset`);
    await stranger.getByTestId('reset-email').fill(`nobody.${RUN}@demo.test`);
    await stranger.getByTestId('reset-send').click();
    await expect(stranger.getByTestId('reset-sent')).toBeVisible();
  } finally {
    const admin = await keycloakAdmin();
    const id = await keycloakUserId(admin, PERSON.email);
    if (id !== null) await admin(`/users/${id}`, { method: 'DELETE' });
  }
});
