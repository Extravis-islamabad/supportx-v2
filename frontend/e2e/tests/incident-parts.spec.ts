import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

/**
 * WP-020e end to end: a task added in one window shows in another live with "done / total";
 * time logged shows its totals; a link made from one incident shows on both.
 *
 * Suite-owned data only ("E2E parts …" incidents, trashed afterwards).
 */

const stamp = String(Date.now()).slice(-7);
const made: string[] = [];

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
  };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function incident(page: Page, subject: string): Promise<{ id: string; display_id: string }> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    user: { id: string };
  };
  const created = await call(page, 'POST', '/incidents', { subject, requester_id: me.user.id });
  expect(created.status(), await created.text()).toBe(201);
  const item = (await created.json()) as { id: string; display_id: string };
  made.push(item.id);
  return item;
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

test('REQ-INC-072 AC1/AC2: tasks show live in a second window, in the saved order', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const first = await browser.newContext();
  const second = await browser.newContext();
  const one = await first.newPage();
  const two = await second.newPage();
  await signInAs(one, 'admin');
  await signInAs(two, 'admin');
  const item = await incident(one, `E2E parts ${stamp} tasks`);
  for (const page of [one, two]) {
    await page.goto(`/incidents/${item.id}`);
    await page.getByRole('tab', { name: /^Tasks/ }).click();
  }
  await one.getByTestId('inc-task-title').fill('Check the cable');
  await one.getByTestId('inc-task-add').click();
  await one.getByTestId('inc-task-title').fill('Swap the printer');
  await one.getByTestId('inc-task-add').click();
  // The other window follows with no reload (AC1).
  await expect(two.getByTestId('inc-tasks-count')).toHaveText('Done: 0 of 2');
  await expectAccessible(one, 'tasks tab');
  await one.getByTestId('inc-task-up-1').click(); // AC2: the new order is saved for everyone
  await expect(two.getByTestId('inc-task-0')).toContainText('Swap the printer');
  await one.getByTestId('inc-task-status-1').click();
  await one.locator('.ant-select-dropdown:visible').getByTitle('Done').click();
  await expect(two.getByTestId('inc-tasks-count')).toHaveText('Done: 1 of 2');
  await expect(two.getByTestId('inc-tab-tasks')).toHaveText('Tasks 1/2');
  await first.close();
  await second.close();
});

test('REQ-INC-067 AC3, REQ-INC-084 AC1: time totals, and a link on both incidents', async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInAs(page, 'admin');
  const first = await incident(page, `E2E parts ${stamp} printer`);
  const second = await incident(page, `E2E parts ${stamp} toner`);
  const read = (await (await call(page, 'GET', `/incidents/${first.id}`)).json()) as {
    id: string;
  };
  const logged = await call(page, 'POST', `/incidents/${read.id}/worklogs`, {
    worklog_type: 'fix',
    started_at: '2026-10-28T09:00:00Z',
    minutes: 90,
  });
  expect(logged.status(), await logged.text()).toBe(201);
  await page.goto(`/incidents/${first.id}`);
  await page.getByRole('tab', { name: 'Worklogs' }).click();
  await expect(page.getByTestId('inc-worklog-totals')).toContainText('1 h 30 min');
  await expect(page.getByTestId('inc-worklog-totals')).toContainText('Fix');

  await page.getByRole('tab', { name: 'Links' }).click();
  await page.getByTestId('inc-link-other').click();
  await page.keyboard.type(second.display_id);
  await page
    .locator('.ant-select-dropdown:visible')
    .getByText(second.display_id, { exact: false })
    .first()
    .click();
  await page.getByTestId('inc-link-comment').fill('Same printer');
  await page.getByTestId('inc-link-add').click();
  await expect(page.getByTestId(`inc-link-${second.display_id}`)).toContainText('Related to');
  await expectAccessible(page, 'links tab');
  // The other incident shows it too, with its history.
  await page.goto(`/incidents/${second.id}`);
  await page.getByRole('tab', { name: 'Links' }).click();
  await expect(page.getByTestId(`inc-link-${first.display_id}`)).toContainText('Same printer');
  await page.getByRole('tab', { name: /^History/ }).click();
  await expect(page.getByTestId('inc-history')).toContainText('Link');
});
