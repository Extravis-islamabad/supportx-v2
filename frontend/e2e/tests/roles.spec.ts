import { expect, test, type Page } from '@playwright/test';

import { deleteE2eRoles, expectAccessible, mainNav, navItems, signInAs } from './helpers';

/** The sections the user's navigation offers, read live (no reload: WP-011 pushes changes). */
async function menu(page: Page): Promise<string[]> {
  await expect(mainNav(page)).toBeVisible();
  return navItems(page);
}

/** Realtime target: a role change reaches the other user's menus within about a second. */
const LIVE = { timeout: 3_000 };

/**
 * WP-016 journey: an admin builds a custom role, gives it to a test user, the user sees exactly
 * the allowed menus; taking the role away takes effect on the user's next request. The role is
 * deleted at the end (suite-owned data only).
 */
test('custom role: create, assign, see the menus, remove', async ({ browser }) => {
  const adminContext = await browser.newContext();
  const userContext = await browser.newContext();
  const admin = await adminContext.newPage();
  const user = await userContext.newPage();
  const roleName = `E2E reports ${String(Date.now())}`;

  // Admin signs in and removes leftovers of an interrupted earlier run (suite-owned roles only).
  await signInAs(admin, 'admin', '/admin/roles');
  await deleteE2eRoles(admin);
  try {
    await journey(admin, user, roleName);
  } finally {
    await deleteE2eRoles(admin);
    await adminContext.close();
    await userContext.close();
  }
});

async function journey(admin: Page, user: Page, roleName: string): Promise<void> {
  // The limited user signs in once (JIT: requester, mapped once from Keycloak).
  await signInAs(user, 'limited');
  expect(await menu(user)).toEqual(['home', 'requests', 'knowledge']);

  // Admin builds the role in Admin › Roles.
  await admin.reload();
  await expect(admin.getByTestId('roles-table').getByText('Tenant administrator')).toBeVisible();
  await expectAccessible(admin, 'roles list');
  await admin.getByTestId('new-role').click();
  await admin.getByTestId('role-name').fill(roleName);
  for (const [permission, scope] of [
    ['problems.view', 'All records'],
    ['reports.view', 'All records'],
  ] as const) {
    await admin.getByTestId(`scope-${permission}`).click();
    await admin.locator(`.ant-select-item-option[title="${scope}"]`).last().click();
  }
  await expectAccessible(admin, 'role editor');
  await admin.screenshot({ path: 'test-results/role-editor.png', fullPage: true });
  await admin.getByTestId('save-role').click();
  await expect(admin.getByText('The role was saved.')).toBeVisible();
  await expect(admin.getByTestId('roles-table').getByText(roleName)).toBeVisible();

  // ...and assigns it in Admin › People (the person drawer's Access tab, WP-021).
  await admin.getByRole('tab', { name: 'People' }).click();
  await admin.getByRole('searchbox', { name: 'Search by name or email' }).fill('e2e.limited');
  await admin.getByText('Lina E2E Limited').click();
  await admin.getByTestId('person-drawer').getByRole('tab', { name: 'Access' }).click();
  const drawer = admin.getByTestId('user-access');
  // Checked once the server confirmed the assignment (the box shows the stored state).
  await drawer.getByLabel(roleName).click();
  await expect(drawer.getByLabel(roleName)).toBeChecked();
  await expectAccessible(admin, 'user access drawer');

  // The user's next request: exactly the role's sections are added (reports.view also opens
  // dashboards: a dashboard is made of reports, WP-036).
  await expect
    .poll(async () => menu(user), LIVE)
    .toEqual(['home', 'requests', 'problems', 'knowledge', 'dashboards', 'reports']);

  // Removing the role takes effect on the next request too.
  await drawer.getByLabel(roleName).click();
  await expect(drawer.getByLabel(roleName)).not.toBeChecked();
  await expect.poll(async () => menu(user), LIVE).toEqual(['home', 'requests', 'knowledge']);
  await user.goto('/problems');
  await expect(user.getByText(/Ask your administrator for access/)).toBeVisible();

  // Clean up: delete the suite's role (nobody holds it any more).
  // Close the drawer with its button: Escape only reaches it while focus is inside, and the
  // checkbox just clicked is briefly disabled (focus falls back to the page) in slow runs.
  await admin
    .getByRole('dialog', { name: 'Lina E2E Limited' })
    .getByRole('button', { name: 'Close' })
    .click();
  await expect(drawer).toBeHidden();
  await admin.getByRole('tab', { name: 'Roles' }).click();
  await admin.getByTestId('roles-table').getByText(roleName).click();
  await admin.getByTestId('delete-role').click();
  await admin
    .getByRole('dialog', { name: `Delete ${roleName}?` })
    .getByRole('button', { name: 'Delete role' })
    .click();
  await expect(admin.getByText('The role was deleted.')).toBeVisible();
}

test('roles page in Arabic and dark mode is accessible', async ({ page }) => {
  await signInAs(page, 'admin', '/admin/roles');
  await expect(page.getByTestId('roles-table')).toBeVisible();
  await page.getByTestId('appearance-menu').click();
  await page.getByText('Dark', { exact: true }).click();
  await page.getByTestId('language-select').click();
  await page.locator('.ant-select-item-option[title="العربية"]').click();
  await page.keyboard.press('Escape');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByTestId('roles-table').getByText('مسؤول المؤسسة')).toBeVisible();
  await expectAccessible(page, 'roles list (Arabic, dark)');
  await page.getByTestId('role-row-technician').click();
  await expect(page.getByText(/لا يمكن تغيير الأدوار المضمّنة/)).toBeVisible();
  await expectAccessible(page, 'role editor (Arabic, dark)');
  await page.screenshot({ path: 'test-results/roles-ar-dark.png', fullPage: true });
});
