import { expect, test, type Browser, type Page } from '@playwright/test';

import { PORTAL_URL } from '../stack';
import { expectAccessible, openAppearance, resetLanguage, signInAs } from './helpers';

/**
 * WP-028: the requester's portal on a phone (REQ-PRT-021, REQ-PRT-022): report an issue, find it
 * in My requests, see a technician's public reply arrive live, confirm the fix; in English and
 * Arabic (right to left), at 360 x 740, with the accessibility check and no sideways scroll.
 * Suite-owned data only: incidents are named "E2E …" and go to the trash at the end (the global
 * teardown hard-deletes them).
 */

const PHONE = { width: 360, height: 740 };
const LIVE = { timeout: 3_000 };

interface Incident {
  id: string;
  display_id: string;
  version: number;
}

async function open(browser: Browser, user: 'admin' | 'limited', path: string, phone = false) {
  const context = await browser.newContext(phone ? { viewport: PHONE } : {});
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

/** The API as the page's signed-in user (same session cookie, CSRF header, If-Match). */
async function call(
  page: Page,
  method: string,
  path: string,
  { body, version }: { body?: unknown; version?: number } = {},
) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function noSidewaysScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, 'the page scrolls sideways at 360 px').toBeLessThanOrEqual(0);
}

async function trash(admin: Page, ids: string[]): Promise<void> {
  for (const id of ids) {
    const found = await call(admin, 'GET', `/incidents/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as Incident;
    await call(admin, 'DELETE', `/incidents/${id}`, { version });
  }
}

test('a requester reports an issue on a phone and follows it live to the fix', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const subject = `E2E Portal ${String(Date.now())}`;
  const requester = await open(browser, 'limited', `${PORTAL_URL}/requests`, true);
  const admin = await open(browser, 'admin', '/');
  const made: string[] = [];
  const page = requester.page;
  try {
    await expect(page.getByTestId('portal-requests')).toBeVisible();
    await expectAccessible(page, 'my requests (phone)');
    await noSidewaysScroll(page);

    // Report an issue: only the requester's fields, the new ID at once (REQ-INC-028 AC1).
    await page.getByTestId('portal-report').click();
    await expect(page.getByTestId('portal-report-subject')).toBeVisible();
    await expectAccessible(page, 'report an issue (phone)');
    await noSidewaysScroll(page);
    await expect(page.getByTestId('portal-report-camera')).toBeVisible(); // REQ-PRT-022 AC3
    await page.getByTestId('portal-report-subject').fill(subject);
    await page.getByTestId('portal-report-send').click();
    await expect(page).toHaveURL(/\/requests\/[0-9a-f-]{36}$/);
    const id = page.url().split('/').at(-1) ?? '';
    made.push(id);
    await expect(page.getByTestId('portal-request-id')).toHaveText(/^INC-\d+$/);
    await expect(page.getByTestId('portal-status')).toHaveText('Received');
    await expectAccessible(page, 'one request (phone)');
    await noSidewaysScroll(page);

    // A technician's public reply appears with no reload (REQ-INC-147 AC3); a private note never.
    const note = await call(admin.page, 'POST', `/incidents/${id}/conversation`, {
      body: { kind: 'note', body: '<p>E2E private triage note</p>' },
    });
    expect(note.status(), await note.text()).toBe(201);
    const reply = await call(admin.page, 'POST', `/incidents/${id}/conversation`, {
      body: { kind: 'reply', body: '<p>E2E: please restart it.</p>' },
    });
    expect(reply.status(), await reply.text()).toBe(201);
    const conversation = page.getByTestId('portal-conversation');
    await expect(conversation.getByText('E2E: please restart it.')).toBeVisible(LIVE);
    await expect(conversation.getByText('E2E private triage note')).toHaveCount(0);

    // The fix: resolved by the technician, confirmed by the requester (REQ-INC-096).
    const current = (await (await call(admin.page, 'GET', `/incidents/${id}`)).json()) as Incident;
    const resolved = await call(admin.page, 'POST', `/incidents/${id}/actions/resolve`, {
      version: current.version,
      body: { resolution: '<p>E2E: reset done.</p>' },
    });
    expect(resolved.status(), await resolved.text()).toBe(200);
    await expect(page.getByTestId('portal-fix')).toBeVisible(LIVE);
    await expectAccessible(page, 'confirm the fix (phone)');
    await page.getByTestId('portal-fix-confirm').click();
    await expect(page.getByTestId('portal-fix')).toBeHidden(LIVE);

    // My requests lists it with its plain status; it never shows staff wording.
    await page.goto(`${PORTAL_URL}/requests`);
    await page.getByTestId('portal-requests-state').getByText('All').click();
    await expect(page.getByTestId('portal-requests').getByText(subject)).toBeVisible();
  } finally {
    await trash(admin.page, made);
    await Promise.all([requester.context.close(), admin.context.close()]);
  }
});

test('the portal in Arabic is right to left and accessible on a phone', async ({ browser }) => {
  const requester = await open(browser, 'limited', `${PORTAL_URL}/requests`, true);
  const page = requester.page;
  try {
    // On a phone the language sits in the appearance menu (the header's compact form).
    await openAppearance(page);
    await page.getByTestId('language-select').click();
    await page.locator('.ant-select-item-option[title="العربية"]').click();
    await page.keyboard.press('Escape');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('portal-report')).toHaveText(/الإبلاغ عن مشكلة/);
    await expectAccessible(page, 'my requests (Arabic, phone)');
    await noSidewaysScroll(page);
    await page.getByTestId('portal-report').click();
    await expect(page.getByTestId('portal-report-subject')).toBeVisible();
    await expectAccessible(page, 'report an issue (Arabic, phone)');
    await noSidewaysScroll(page);
  } finally {
    // The suite user's language is stored with them: back to the identity provider's.
    await resetLanguage(page);
    await requester.context.close();
  }
});
