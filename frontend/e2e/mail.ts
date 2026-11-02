import { expect, type Browser, type Page } from '@playwright/test';

import { stackEnv } from './stack';

// The Compose stack's mail catcher (Mailpit) and Keycloak's set-password pages (WP-039).

function mailpit(): string {
  return (
    process.env.SUPPORTX_E2E_MAIL_URL ??
    `http://localhost:${stackEnv().MAILPIT_WEB_PORT ?? '28025'}`
  );
}

/**
 * Why tests that need e-mail cannot run on this stack, or null when they can. The k3d cluster
 * has no mail sender or catcher yet: lane B adds a dev-profile-only Mailpit right after WP-024,
 * and its e2e script then sets SUPPORTX_E2E_MAIL_URL, which turns these tests back on.
 */
export function mailUnavailable(): string | null {
  const onCluster = process.env.SUPPORTX_E2E_KEYCLOAK_URL !== undefined;
  if (onCluster && process.env.SUPPORTX_E2E_MAIL_URL === undefined) {
    return 'expected skip: the k3d cluster has no mail sender or catcher yet (dev-profile Mailpit follows WP-024)';
  }
  return null;
}

export interface MailSummary {
  ID: string;
  Subject: string;
  From: { Address: string; Name: string };
}

/** The first message to `to` sent after `after` (ms), waiting for it to arrive. */
export async function mailTo(
  to: string,
  after: number,
): Promise<{ summary: MailSummary; html: string }> {
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

/** The set-password link of Keycloak's e-mail. */
export function actionLink(html: string): string {
  const match = /href="([^"]*login-actions\/action-token[^"]*)"/.exec(html);
  expect(match, 'the e-mail has the set-password link').not.toBeNull();
  return (match?.[1] ?? '').replaceAll('&amp;', '&');
}

/** A browser window with nobody signed in. */
export async function privateWindow(browser: Browser): Promise<Page> {
  return (await browser.newContext()).newPage();
}

/** Keycloak's new-password page. */
export async function setPassword(page: Page, password: string): Promise<void> {
  await page.locator('#password-new').fill(password);
  await page.locator('#password-confirm').fill(password);
  await page.locator('input[type=submit], button[type=submit]').first().click();
}
