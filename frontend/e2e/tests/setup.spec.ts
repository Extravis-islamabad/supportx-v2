import { expect, test } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

/**
 * WP-042 session 1: the setup home groups what the admin may change and finds a page by a
 * keyword; the setup menu stays beside every page; the licence page shows the plan in labels.
 * Accessible in light, dark and Arabic (right to left), at 1366 and 390 px.
 */
test('setup home, search, menu and licence page: labelled and accessible', async ({ page }) => {
  test.setTimeout(150_000);
  await page.setViewportSize({ width: 1366, height: 900 });
  await signInAs(page, 'admin', '/admin');
  const home = page.getByTestId('setup-home');
  await expect(home.getByRole('heading', { name: 'People and access' })).toBeVisible();
  await expectAccessible(page, 'setup home');

  // A synonym finds the page; the menu stays and marks where you are.
  // The test id is on the <input> itself (Ant's Input.Search passes it down).
  await page.getByTestId('setup-search').fill('2fa');
  await expect(home.getByTestId('setup-page-security')).toBeVisible();
  await expect(home.getByTestId('setup-page-users')).toHaveCount(0);
  await page.getByTestId('admin-sections').getByRole('link', { name: 'Licence and plan' }).click();
  await expect(page).toHaveURL(/\/admin\/licence$/);
  await expect(page.getByTestId('admin-sections-licence')).toHaveAttribute('aria-current', 'page');
  const licence = page.getByTestId('licence-page');
  await expect(licence.getByTestId('licence-limits')).toContainText('Technicians');
  await expect(licence).not.toContainText(/\btechnicians\b|entitlement_|limit\./);
  await expectAccessible(page, 'licence page');

  // Dark and Arabic.
  await page.getByTestId('appearance-menu').click();
  await page.getByText('Dark', { exact: true }).click();
  await page.getByTestId('language-select').click();
  await page.locator('.ant-select-item-option[title="العربية"]').click();
  await page.keyboard.press('Escape');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expectAccessible(page, 'licence page (Arabic, dark)');
  await page.goto('/admin');
  await expect(page.getByTestId('setup-home')).toBeVisible();
  await expectAccessible(page, 'setup home (Arabic, dark)');

  // A phone width: the sections open from a button, in a drawer (QA6S-SHELL-04).
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId('admin-sections-button').click();
  await expect(page.getByTestId('admin-sections')).toBeVisible();
  await expectAccessible(page, 'setup home (390 px)');
});
