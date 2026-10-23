import { expect, test } from '@playwright/test';

import { signInAs } from './helpers';

test('users list: search, filter, sort and infinite scroll against the real API', async ({
  page,
}) => {
  await signInAs(page, 'admin');
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByText('Admin', { exact: true })
    .click();
  await expect(page.getByRole('heading', { name: 'Users', level: 1 })).toBeVisible();
  const table = page.getByTestId('users-table');
  const rows = table.locator('tbody tr.ant-table-row');

  // 40 fixture requesters + the realm users: the first page holds 25, scrolling loads the rest.
  await expect(rows).toHaveCount(25);
  await page.getByTestId('users-sentinel').scrollIntoViewIfNeeded();
  await expect.poll(async () => rows.count()).toBeGreaterThan(40);
  await page.getByTestId('users-sentinel').scrollIntoViewIfNeeded();
  await expect(page.getByTestId('users-end')).toBeVisible();

  await page.getByRole('searchbox', { name: 'Search by name or email' }).fill('scroll 07');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('E2E Scroll 07');
  await expect(rows.first()).toContainText('Requester'); // a label, never the code
  await page.getByRole('searchbox', { name: 'Search by name or email' }).fill('');

  await page.getByTestId('users-filter-type').click();
  await page.locator('.ant-select-item-option[title="Technician"]').click();
  await expect(rows.filter({ hasText: 'E2E Scroll' })).toHaveCount(0);
  await expect(rows.filter({ hasText: 'Adel E2E Admin' })).toHaveCount(1);

  await page.getByTestId('users-sort').click();
  await page.locator('.ant-select-item-option[title="Name (Z–A)"]').click();
  const names = await rows.locator('td:first-child').allTextContents();
  expect(names).toEqual([...names].sort((a, b) => b.localeCompare(a)));
  await page.screenshot({ path: 'test-results/users-list.png', fullPage: true });
});
