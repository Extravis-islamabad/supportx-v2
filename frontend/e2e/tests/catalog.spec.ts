import { expect, test, type Browser, type Page } from '@playwright/test';

import { PORTAL_URL } from '../stack';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-031: build an item in Admin › Service catalog, preview it as a requester sees it, publish
 * it, and request it in the portal, where it appears without a reload (live).
 *
 * Suite-owned data only: the category, group, item and request are named "E2E …"; the request
 * goes to the trash and the item is retired at the end (the fixtures teardown removes them).
 */

const LIVE = { timeout: 5_000 };

async function open(browser: Browser, user: 'admin' | 'limited', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

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

/** Choose `text` in the Ant Design select with this test ID. */
async function choose(page: Page, testId: string, text: string) {
  await page.getByTestId(testId).click();
  await page
    .locator('.ant-select-dropdown:visible')
    .getByText(text, { exact: true })
    .first()
    .click();
}

test('build, preview, publish and request a catalog item, live in the portal', async ({
  browser,
}) => {
  const tag = crypto.randomUUID().slice(0, 8);
  const name = `E2E monitor ${tag}`;
  const admin = await open(browser, 'admin', '/admin/catalog');
  const requester = await open(browser, 'limited', `${PORTAL_URL}/catalog`);
  let itemId: string | undefined;
  let requestId: string | undefined;
  try {
    // A category and a fulfilment group of the suite's own.
    const category = await call(admin.page, 'POST', '/catalog/categories', {
      body: { names: { en: `E2E screens ${tag}` } },
    });
    expect(category.status(), await category.text()).toBe(201);
    const group = await call(admin.page, 'POST', '/organization/groups', {
      body: { name: `E2E catalog desk ${tag}` },
    });
    expect(group.status(), await group.text()).toBe(201);

    // 1. Build: a new item with a name, its category, a required question and its group.
    await admin.page.getByTestId('cat-new-item').click();
    await admin.page.getByTestId('cat-name-en').fill(name);
    await choose(admin.page, 'cat-category', `E2E screens ${tag}`);
    await admin.page.getByRole('tab', { name: 'Form' }).click();
    await admin.page.getByTestId('cat-question-add').click();
    await admin.page.getByTestId('cat-question-0-label-en').fill('Which desk');
    await admin.page.getByTestId('cat-question-0-key').fill('desk');
    await admin.page
      .getByTestId('cat-question-0')
      .getByRole('switch', { name: 'Required' })
      .click();
    await admin.page.getByRole('tab', { name: 'SLA and assignment' }).click();
    await choose(admin.page, 'cat-group', `E2E catalog desk ${tag}`);
    await admin.page.getByTestId('cat-save').click();
    await expect(admin.page).toHaveURL(/\/admin\/catalog\/items\/[0-9a-f-]{36}$/, LIVE);
    itemId = admin.page.url().split('/').pop();
    await expectAccessible(admin.page, 'catalog item page');

    // Still a draft: the requester's catalog does not offer it.
    await requester.page.getByTestId('portal-cat-search').fill(name);
    await expect(requester.page.getByTestId('portal-cat-no-match')).toBeVisible(LIVE);

    // 2. Preview: the form as a requester sees it, nothing can be sent.
    await admin.page.getByTestId('cat-preview').click();
    const preview = admin.page.getByTestId('cat-preview-drawer');
    await expect(preview.getByText('Which desk')).toBeVisible();
    await expect(preview.getByTestId('sr-q-desk')).toBeDisabled();
    await admin.page.keyboard.press('Escape');

    // 3. Publish: it reaches the open portal search without a reload.
    await admin.page.getByRole('tab', { name: 'Publishing' }).click();
    await admin.page.getByTestId('cat-publish').click();
    await expect(admin.page.getByTestId(`cat-status-${itemId ?? ''}`)).toHaveText(
      'Published',
      LIVE,
    );
    await requester.page.getByTestId('portal-cat-search').fill(`${name} `);
    await expect(requester.page.getByTestId(`portal-cat-item-${itemId ?? ''}`)).toBeVisible(LIVE);

    // 4. Request it: the form needs the answer, the request opens at once.
    await requester.page.getByTestId(`portal-cat-item-${itemId ?? ''}`).click();
    await expect(requester.page.getByTestId('portal-cat-send')).toBeDisabled();
    await requester.page.getByTestId('portal-cat-subject').fill(`E2E monitor for Lina ${tag}`);
    await requester.page.getByTestId('sr-q-desk').fill('Desk 12');
    await expectAccessible(requester.page, 'portal catalog item');
    await requester.page.getByTestId('portal-cat-send').click();
    await expect(requester.page).toHaveURL(/\/service-requests\/[0-9a-f-]{36}$/, LIVE);
    requestId = requester.page.url().split('/').pop();
    await expect(requester.page.getByTestId('portal-service-request-answers')).toContainText(
      'Desk 12',
    );
  } finally {
    if (requestId !== undefined) {
      const found = await call(admin.page, 'GET', `/service-requests/${requestId}`);
      if (found.status() === 200) {
        const { version } = (await found.json()) as { version: number };
        await call(admin.page, 'DELETE', `/service-requests/${requestId}`, { version });
      }
    }
    if (itemId !== undefined) {
      const found = await call(admin.page, 'GET', `/catalog/items/${itemId}`);
      if (found.status() === 200) {
        const { version, status } = (await found.json()) as { version: number; status: string };
        if (status === 'published') {
          await call(admin.page, 'PATCH', `/catalog/items/${itemId}`, {
            body: { status: 'retired' },
            version,
          });
        }
      }
    }
    await Promise.all([admin.context.close(), requester.context.close()]);
  }
});
