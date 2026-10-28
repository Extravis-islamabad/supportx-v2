import { expect, test, type Page } from '@playwright/test';

import { openSelect, signInAs } from './helpers';

/**
 * WP-029-FIX: the findings of the WP-029 QA report that need the real stack, named after their
 * IDs. Nothing is mocked: a business rule saved through the API refuses a save made on screen.
 *
 * Suite-owned data only: the rule matches only subjects carrying this run's stamp and is
 * removed afterwards; nothing is created when the rule refuses.
 */

const stamp = () => String(Date.now()).slice(-7);

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

const rules: { id: string; version: number }[] = [];

test.afterAll(async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, 'admin');
  for (const rule of rules) {
    await call(page, 'DELETE', `/automation/rules/${rule.id}`, undefined, rule.version);
  }
  await context.close();
});

test('BUG-01, BUG-02: a rule refusing a save shows its own message once, at the form', async ({
  page,
}) => {
  const tag = stamp();
  const message = `E2E ${tag}: pick the site the printer is at.`;
  await signInAs(page, 'admin', '/incidents/new');
  const created = await call(page, 'POST', '/automation/rules', {
    record_type: 'incident',
    name: `E2E refuse ${tag}`,
    events: ['create'],
    state: 'enabled',
    conditions: { field: 'subject', op: 'contains', value: tag },
    actions: [{ kind: 'refuse', message: { en: message }, mode: 'fill_empty' }],
  });
  expect(created.status(), await created.text()).toBe(201);
  rules.push((await created.json()) as { id: string; version: number });

  await page.reload();
  await page.getByTestId('inc-subject').fill(`E2E printer ${tag}`);
  const requester = page.getByTestId('inc-requester');
  const list = await openSelect(page, 'inc-requester');
  await requester.locator('input').fill('E2E Admin');
  await list
    .getByText(/^Adel E2E Admin$/)
    .first()
    .click();
  await page.getByTestId('inc-save').click();

  const problem = page.getByTestId('form-problem');
  await expect(problem).toContainText(message);
  await expect(page.getByText(message)).toHaveCount(1);
  await expect(page.locator('body')).not.toContainText('{{');
  // An expected refusal, not a failure: no error toast, no support reference.
  await expect(page.locator('.ant-notification-notice')).toHaveCount(0);
  await expect(page.getByText('Copy reference')).toHaveCount(0);
  // The form keeps what was typed, on the same page.
  await expect(page).toHaveURL(/\/incidents\/new$/);
  await expect(page.getByTestId('inc-subject')).toHaveValue(`E2E printer ${tag}`);
});
