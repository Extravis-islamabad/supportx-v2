import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, openSelect, signInAs } from './helpers';

/**
 * WP-020f end to end: resolve with a resolution and close with a closure code on screen, the
 * record shows both; reopening keeps them in the history and asks again next time.
 *
 * Suite-owned data only ("E2E closing …" incidents, trashed afterwards).
 */

const stamp = () => String(Date.now()).slice(-7);
const made: string[] = [];

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

test.afterAll(async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, 'admin');
  for (const id of made) {
    const found = await call(page, 'GET', `/incidents/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as { version: number };
    await call(page, 'DELETE', `/incidents/${id}`, undefined, version);
  }
  await context.close();
});

test('REQ-INC-090/093/097: resolve with a resolution, close with a code, reopen keeps the past', async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInAs(page, 'admin', '/incidents');
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    user: { id: string };
  };
  const created = await call(page, 'POST', '/incidents', {
    subject: `E2E closing ${stamp()}`,
    requester_id: me.user.id,
  });
  expect(created.status(), await created.text()).toBe(201);
  const item = (await created.json()) as { id: string };
  made.push(item.id);
  await page.goto(`/incidents/${item.id}`);

  // Resolve: the dialog asks for a resolution first.
  await page.getByTestId('inc-action-resolve').click();
  await page.getByTestId('inc-reason-confirm').click();
  await expect(page.getByTestId('inc-resolution-error')).toBeVisible();
  await page
    .getByTestId('inc-resolution-editor')
    .locator('[contenteditable="true"]')
    .fill('Restarted the print spooler.');
  await expectAccessible(page, 'resolve dialog');
  await page.getByTestId('inc-reason-confirm').click();
  await expect(page.getByTestId('inc-resolution')).toContainText('Restarted the print spooler.');

  // Close: a closure code, shown on the record in words.
  await page.getByTestId('inc-action-close').click();
  const list = await openSelect(page, 'inc-closure-code');
  await list.getByTitle('Workaround given').click();
  await page.getByTestId('inc-reason-confirm').click();
  await expect(page.getByTestId('inc-closure-code-view')).toContainText('Workaround given');

  // Reopen (a reason is asked): the current values clear, history keeps them.
  await page.getByTestId('inc-action-reopen').click();
  const reasons = await openSelect(page, 'inc-reason-code');
  await reasons.locator('.ant-select-item-option').first().click();
  await page.getByTestId('inc-reason-text').fill('Still jams.');
  await page.getByTestId('inc-reason-confirm').click();
  await expect(page.getByTestId('inc-resolution-card')).toHaveCount(0);
  await page.getByRole('tab', { name: /History/ }).click();
  await expect(page.getByTestId('inc-history-entry').first()).toBeVisible();
  await expect(page.locator('[data-testid="inc-history-entry"]')).toContainText([
    /Workaround given/,
  ]);
});
