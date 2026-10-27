import { expect, test, type Browser } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

/**
 * WP-021 end to end: an admin adds a contact (no sign-in, no email); a second admin's People
 * list shows it live; the contact is deactivated with a confirmation. A department is added,
 * appears live on the other admin's Organisation page, and is removed (nothing uses it).
 *
 * Suite-owned data only: people and departments named "E2E …" that never signed in;
 * global-teardown removes them (tooling/e2e_fixtures.py).
 */

const LIVE = { timeout: 8_000 };
const stamp = () => String(Date.now()).slice(-7);

async function open(browser: Browser, path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, 'admin', path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

test('people: a contact is added, shows live elsewhere and is deactivated', async ({ browser }) => {
  test.setTimeout(120_000);
  const name = `E2E Contact ${stamp()}`;
  const first = await open(browser, '/admin/users');
  const second = await open(browser, '/admin/users');
  const a = first.page;
  const b = second.page;

  await a.getByTestId('people-add').click();
  await a.getByTestId('person-first-name').fill(name);
  await a.getByTestId('person-can-sign-in').click(); // a contact: no sign-in, no email needed
  await expectAccessible(a, 'add person');
  await a.getByTestId('person-save').click();
  await expect(a.getByText(`${name} added`)).toBeVisible();

  // The other admin's list (default view: active people) shows the new contact without reload.
  await b.getByRole('searchbox', { name: 'Search by name or email' }).fill(name);
  const row = b.getByTestId('users-table').locator('tbody tr', { hasText: name });
  await expect(row).toBeVisible(LIVE);
  await expect(row).toContainText('Contact'); // a label, never can_sign_in=false

  await a.getByRole('searchbox', { name: 'Search by name or email' }).fill(name);
  await a.getByTestId('users-table').getByText(name).click();
  const drawer = a.getByTestId('person-drawer');
  await expectAccessible(a, 'person drawer');
  await drawer.getByTestId('person-deactivate').click();
  await a.locator('.ant-popconfirm').getByRole('button', { name: 'Deactivate' }).click();
  await expect(drawer.getByTestId('person-deactivated')).toBeVisible();
  // Deactivated people leave the "Active people" view on the other screen, live.
  await expect(row).toBeHidden(LIVE);

  await first.context.close();
  await second.context.close();
});

test('organisation: a department appears live and an unused one can be removed', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const name = `E2E Dept ${stamp()}`;
  const first = await open(browser, '/admin/organization/departments');
  const second = await open(browser, '/admin/organization/departments');
  const a = first.page;
  const b = second.page;

  await a.getByTestId('departments-add').click();
  await a.getByTestId('unit-name').fill(name);
  await a.getByTestId('unit-code').fill(`e2e-${stamp()}`);
  await a.getByTestId('unit-save').click();
  await expect(a.getByTestId('departments-table').getByText(name)).toBeVisible();
  await expect(b.getByTestId('departments-table').getByText(name)).toBeVisible(LIVE);
  await expectAccessible(b, 'organisation departments');

  await a.getByTestId(`departments-remove-${name}`).click();
  await a.locator('.ant-popconfirm').getByRole('button', { name: 'Remove' }).click();
  await expect(a.getByText(`${name} removed`)).toBeVisible();
  await expect(b.getByTestId('departments-table').getByText(name)).toBeHidden(LIVE);

  await first.context.close();
  await second.context.close();
});
