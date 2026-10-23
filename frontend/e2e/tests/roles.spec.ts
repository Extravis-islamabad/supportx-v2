import { expect, test, type Page } from '@playwright/test';

import { deleteE2eRoles, expectAccessible, signInAs } from './helpers';

async function menu(page: Page): Promise<string[]> {
  await page.reload();
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(nav.getByText('Home', { exact: true })).toBeVisible();
  return nav.getByRole('menuitem').allTextContents();
}

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
  expect(await menu(user)).toEqual(['Home', 'Requests', 'Knowledge']);

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

  // ...and assigns it in Admin › Users.
  await admin.getByRole('tab', { name: 'Users' }).click();
  await admin.getByRole('searchbox', { name: 'Search by name or email' }).fill('e2e.limited');
  await admin.getByText('Lina E2E Limited').click();
  const drawer = admin.getByTestId('user-access');
  // Checked once the server confirmed the assignment (the box shows the stored state).
  await drawer.getByLabel(roleName).click();
  await expect(drawer.getByLabel(roleName)).toBeChecked();
  await expectAccessible(admin, 'user access drawer');

  // The user's next request: exactly the role's sections are added.
  await expect
    .poll(async () => menu(user))
    .toEqual(['Home', 'Requests', 'Problems', 'Knowledge', 'Reports']);

  // Removing the role takes effect on the next request too.
  await drawer.getByLabel(roleName).click();
  await expect(drawer.getByLabel(roleName)).not.toBeChecked();
  await expect.poll(async () => menu(user)).toEqual(['Home', 'Requests', 'Knowledge']);
  await user.goto('/problems');
  await expect(user.getByText(/Ask your administrator for access/)).toBeVisible();

  // Clean up: delete the suite's role (nobody holds it any more).
  await admin.keyboard.press('Escape');
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
