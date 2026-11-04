import { expect, test, type Browser, type Page } from '@playwright/test';

import { mailTo, mailUnavailable } from '../mail';
import { PORTAL_URL, USERS } from '../stack';
import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-030: service requests from the catalog, end to end.
 *
 * 1. A requester raises a request; it waits for the technician's approval; the technician
 *    approves it from the console's approvals drawer; the item's plan becomes a task; the
 *    technician ticks it done; the request is fulfilled; the requester confirms receipt in the
 *    portal. Each screen follows live, with no reload.
 * 2. A requester-only approver gets the approval by e-mail, opens the signed link in the portal,
 *    and approves there (lane B's conditions: the token only in the URL fragment, one use).
 * 3. The portal's service request pages in Arabic: right to left, accessible.
 *
 * Suite-owned data only: items and requests are named "E2E …"; the requests go to the trash and
 * the items are disabled at the end.
 */

const LIVE = { timeout: 5_000 };

interface Made {
  id: string;
  display_id: string;
  version: number;
}

async function open(browser: Browser, user: 'admin' | 'tech' | 'limited', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

/** The page's own origin: the portal's session cookie belongs to the portal's origin. */
function origin(page: Page): string {
  return new URL(page.url()).origin;
}

/** The API as the page's signed-in user (same session cookie, CSRF header, If-Match). */
async function call(
  page: Page,
  method: string,
  path: string,
  { body, version }: { body?: unknown; version?: number } = {},
) {
  const base = origin(page);
  const me = (await (await page.request.get(`${base}/api/v1/auth/me`)).json()) as {
    csrf_token: string;
  };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`${base}/api/v1${path}`, { method, data: body, headers });
}

async function userId(page: Page): Promise<string> {
  const me = (await (await page.request.get(`${origin(page)}/api/v1/auth/me`)).json()) as {
    user: { id: string };
  };
  return me.user.id;
}

async function item(admin: Page, name: string, approverId: string): Promise<Made> {
  const made = await call(admin, 'POST', '/catalog/items', {
    body: {
      names: { en: name, ar: name },
      approval: { approvers: [{ kind: 'person', person_id: approverId }] },
      plan: [{ title: { en: `${name}: hand it over` } }],
      default_priority: 'p3',
    },
  });
  expect(made.status(), await made.text()).toBe(201);
  return (await made.json()) as Made;
}

async function raise(requester: Page, itemId: string, subject: string): Promise<Made> {
  const made = await call(requester, 'POST', '/service-requests', {
    body: {
      subject,
      requester_id: await userId(requester),
      catalog_item_id: itemId,
      answers: {},
      confirm_lose_access: false,
    },
  });
  expect(made.status(), await made.text()).toBe(201);
  return (await made.json()) as Made;
}

async function cleanUp(admin: Page, requests: string[], items: string[]): Promise<void> {
  for (const id of requests) {
    const found = await call(admin, 'GET', `/service-requests/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as Made;
    await call(admin, 'DELETE', `/service-requests/${id}`, { version });
  }
  for (const id of items) {
    const found = await call(admin, 'GET', `/catalog/items/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as Made;
    await call(admin, 'PATCH', `/catalog/items/${id}`, { body: { enabled: false }, version });
  }
}

test('raise, approve from the drawer, fulfil and confirm receipt, all live', async ({
  browser,
}) => {
  const tag = crypto.randomUUID().slice(0, 8);
  const admin = await open(browser, 'admin', '/');
  const tech = await open(browser, 'tech', '/requests');
  const requester = await open(browser, 'limited', `${PORTAL_URL}/service-requests`);
  const made: string[] = [];
  const items: string[] = [];
  try {
    const laptop = await item(admin.page, `E2E laptop ${tag}`, await userId(tech.page));
    items.push(laptop.id);
    const record = await raise(requester.page, laptop.id, `E2E laptop for Lina ${tag}`);
    made.push(record.id);

    // The requester's list shows it waiting for approval, live.
    const row = requester.page.getByTestId(`portal-service-request-${record.display_id}`);
    await expect(row).toContainText('Waiting for approval', LIVE);

    // The technician's drawer counts it; approving removes it.
    await expect(tech.page.getByRole('button', { name: /approvals? waiting for you/ })).toBeVisible(
      LIVE,
    );
    await tech.page.getByTestId('approvals-drawer-open').click();
    const entry = tech.page.getByTestId(`my-approval-${record.display_id}`);
    await entry.getByRole('button', { name: 'Approve' }).click();
    // The drawer is a dialog too: the decision is the dialog named "Approve".
    await tech.page
      .getByRole('dialog', { name: 'Approve' })
      .getByRole('button', { name: 'Approve' })
      .click();
    await expect(entry).toBeHidden(LIVE);

    // The plan became a task on the request; ticking it fulfils the request.
    await tech.page.goto(`/requests/${record.id}`);
    const task = tech.page.getByRole('checkbox', { name: `E2E laptop ${tag}: hand it over` });
    // The box follows the saved task (a controlled checkbox): click, then wait for the save.
    await task.click();
    await expect(task).toBeChecked(LIVE);

    // The requester sees it fulfilled without a reload, and confirms receipt.
    await row.getByRole('link').click();
    await expect(requester.page.getByTestId('portal-status')).toHaveText(
      'Resolved: please confirm',
      LIVE,
    );
    await requester.page.getByTestId('portal-receipt-confirm').click();
    await expect(requester.page.getByTestId('portal-status')).toHaveText('Closed', LIVE);
  } finally {
    await cleanUp(admin.page, made, items);
    await Promise.all([admin.context.close(), tech.context.close(), requester.context.close()]);
  }
});

test('a requester-only approver approves from the e-mailed link in the portal', async ({
  browser,
}) => {
  const noMail = mailUnavailable();
  test.skip(noMail !== null, noMail ?? '');
  const tag = crypto.randomUUID().slice(0, 8);
  const admin = await open(browser, 'admin', '/');
  const approver = await open(browser, 'limited', `${PORTAL_URL}/approvals`);
  const made: string[] = [];
  const items: string[] = [];
  try {
    const desk = await item(admin.page, `E2E desk ${tag}`, await userId(approver.page));
    items.push(desk.id);
    const sentAt = Date.now() - 1_000;
    const record = await raise(admin.page, desk.id, `E2E desk for Adel ${tag}`);
    made.push(record.id);

    // The portal inbox has it, live.
    await expect(approver.page.getByTestId(`portal-approval-${record.display_id}`)).toBeVisible(
      LIVE,
    );

    // The e-mail carries this approver's own link: the token only after '#'.
    const mail = await mailTo(USERS.limited.email, sentAt);
    const link = /https?:\/\/[^"\s<]*(requests\/approval-link#[A-Za-z0-9_-]{43})/.exec(mail.html);
    expect(link, 'the e-mail has the approval link').not.toBeNull();
    // Deployed, the portal is served on the tenant's origin under /portal/, which is where the
    // link points; the dev stack serves it on a port of its own, so the path and token are
    // opened on the suite's portal (lane B: email_branding on the dev stack).
    const url = `${PORTAL_URL}/${link?.[1] ?? ''}`;
    await approver.page.goto(url);
    await expect(approver.page.getByTestId('approval-link-summary')).toContainText(
      record.display_id,
    );
    expect(new URL(approver.page.url()).hash).toBe(''); // gone from the address bar
    await approver.page.getByTestId('approval-link-approve').click();
    await expect(approver.page.getByTestId('approval-link-done')).toBeVisible(LIVE);

    // Once used, the link does nothing more (from a fresh load, not a same-page hash change).
    await approver.page.goto(`${PORTAL_URL}/approvals`);
    await approver.page.goto(url);
    await expect(approver.page.getByTestId('approval-link-refused')).toContainText(
      'already been used',
    );
    const after = (await (
      await call(admin.page, 'GET', `/service-requests/${record.id}`)
    ).json()) as { approval_status: string };
    expect(after.approval_status).toBe('approved');
  } finally {
    await cleanUp(admin.page, made, items);
    await Promise.all([admin.context.close(), approver.context.close()]);
  }
});

test('the portal service request pages in Arabic are right to left and accessible', async ({
  browser,
}) => {
  const tag = crypto.randomUUID().slice(0, 8);
  const admin = await open(browser, 'admin', '/');
  const requester = await open(browser, 'limited', `${PORTAL_URL}/service-requests`);
  const made: string[] = [];
  const items: string[] = [];
  try {
    const chair = await item(admin.page, `E2E chair ${tag}`, await userId(admin.page));
    items.push(chair.id);
    const record = await raise(requester.page, chair.id, `E2E chair ${tag}`);
    made.push(record.id);
    const page = requester.page;
    await page.getByTestId('appearance-menu').click();
    await page.getByTestId('language-select').click();
    await page.locator('.ant-select-item-option[title="العربية"]').click();
    await page.keyboard.press('Escape');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    const row = page.getByTestId(`portal-service-request-${record.display_id}`);
    await expect(row).toContainText('بانتظار الموافقة', LIVE);
    await expectAccessible(page, 'my service requests (Arabic)');
    await row.getByRole('link').click();
    await expect(page.getByTestId('portal-withdraw')).toBeVisible();
    await expectAccessible(page, 'one service request (Arabic)');
    await page.goto(`${PORTAL_URL}/approvals`);
    await expect(page.getByTestId('portal-approvals')).toBeVisible();
    await expectAccessible(page, 'approvals (Arabic)');
  } finally {
    // The suite user's language is stored with them: back to the identity provider's.
    await resetLanguage(requester.page);
    await cleanUp(admin.page, made, items);
    await Promise.all([admin.context.close(), requester.context.close()]);
  }
});
