import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, openSelect, signInAs } from './helpers';

/**
 * WP-020d end to end: a saved view built with the filter builder lists exactly its incidents and
 * keeps its own columns; a bulk close of selected incidents closes the ones that have a closure
 * code and lists the others with the reason, live.
 *
 * Suite-owned data only ("E2E list …" incidents and the view, removed afterwards).
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
  const views = (await (await call(page, 'GET', '/incidents/saved-views')).json()) as {
    id: string;
    name: string;
    version: number;
    mine: boolean;
  }[];
  for (const view of views.filter((v) => v.mine && v.name.startsWith('E2E list'))) {
    await call(page, 'DELETE', `/incidents/saved-views/${view.id}`, undefined, view.version);
  }
  await context.close();
});

test('REQ-INC-106: a view built with the filter builder lists exactly its incidents', async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInAs(page, 'admin', '/incidents');
  const wanted = await incident(page, `E2E list ${stamp} printer`);
  const other = await incident(page, `E2E list ${stamp} mail`);

  await page.getByTestId('inc-view-new').click();
  await page.getByTestId('inc-view-name').fill(`E2E list ${stamp}`);
  await page.getByTestId('inc-view-filter-add').click();
  const fields = await openSelect(page, 'inc-view-filter-field-0');
  // The field list is long and virtual: search it, as people do.
  await page.keyboard.type('Subject');
  await fields.getByTitle('Subject', { exact: true }).click();
  await page.getByTestId('inc-view-filter-value-0').fill(`E2E list ${stamp} printer`);
  await expectAccessible(page, 'view editor');

  // AC2: applying without saving changes only this screen.
  await page.getByTestId('inc-view-try').click();
  await expect(page.getByTestId('inc-trying')).toBeVisible();
  await expect(page.getByTestId(`inc-row-${wanted.display_id}`)).toBeVisible();
  await expect(page.getByTestId(`inc-row-${other.display_id}`)).toHaveCount(0);

  // Saved, it is a view of its own; the rows are the same (AC3).
  await page.getByTestId('inc-view-new').click();
  await page.getByTestId('inc-view-name').fill(`E2E list ${stamp}`);
  await page.getByTestId('inc-view-filter-add').click();
  const again = await openSelect(page, 'inc-view-filter-field-0');
  // The field list is long and virtual: search it, as people do.
  await page.keyboard.type('Subject');
  await again.getByTitle('Subject', { exact: true }).click();
  await page.getByTestId('inc-view-filter-value-0').fill(`E2E list ${stamp} printer`);
  await page.getByTestId('inc-view-save').click();
  await expect(page.getByTestId('inc-view')).toContainText(`E2E list ${stamp}`);
  await expect(page.getByTestId(`inc-row-${wanted.display_id}`)).toBeVisible();
  await expect(page.getByTestId(`inc-row-${other.display_id}`)).toHaveCount(0);

  // Its own columns (REQ-INC-104 AC3): adding one here leaves "All open" as it was.
  await page.getByTestId('inc-columns').click();
  await page.getByTestId('inc-columns-search').fill('Created');
  await page.getByTestId('inc-column-add-created_at').click();
  await expect(page.getByTestId('inc-column-created_at')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('columnheader', { name: 'Created' })).toBeVisible();
  await page.reload(); // AC1: kept for this user after a reload
  const views = await openSelect(page, 'inc-view');
  await views.getByTitle(`E2E list ${stamp}`).click();
  await expect(page.getByRole('columnheader', { name: 'Created' })).toBeVisible();
});

test('REQ-INC-120 AC1: a bulk close closes what it may and lists the rest with the reason', async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInAs(page, 'admin', '/incidents');
  const items = [
    await incident(page, `E2E list ${stamp} bulk a`),
    await incident(page, `E2E list ${stamp} bulk b`),
    await incident(page, `E2E list ${stamp} bulk c`),
  ];
  for (const [index, item] of items.entries()) {
    const read = (await (await call(page, 'GET', `/incidents/${item.id}`)).json()) as {
      version: number;
    };
    const resolved = await call(
      page,
      'POST',
      `/incidents/${item.id}/actions/resolve`,
      {
        resolution: '<p>Fixed.</p>',
        // The first one already carries a closure code; the others do not.
        ...(index === 0 ? { closure_code: 'fixed' } : {}),
      },
      read.version,
    );
    expect(resolved.status(), await resolved.text()).toBe(200);
  }
  await page.getByTestId('inc-search').fill(`E2E list ${stamp} bulk`);
  const views = await openSelect(page, 'inc-view');
  await views.getByTitle(/^Resolved, awaiting confirmation/).click();
  for (const item of items) {
    await page.getByTestId(`inc-row-${item.display_id}`).getByRole('checkbox').check();
  }
  await expect(page.getByTestId('inc-selected')).toHaveText('3 incidents selected');
  await page.getByTestId('inc-bulk-close').click();
  await expectAccessible(page, 'bulk close dialog');
  await page.getByTestId('inc-bulk-start').click();
  await expect(page.getByTestId('inc-bulk-status')).toHaveText('Finished: 1 changed, 2 skipped.', {
    timeout: 60_000,
  });
  const skipped = page.getByTestId('inc-bulk-skipped');
  await expect(skipped.getByText('Closure code: This field is required.')).toHaveCount(2);
  // AC3: the result is findable after leaving the page.
  await page.goto('/incidents');
  await page.getByTestId('inc-bulk-jobs').click();
  await expect(page.getByText('Close 3 incidents').first()).toBeVisible();
});
