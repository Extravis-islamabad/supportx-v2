import { expect, test } from '@playwright/test';

import { deleteE2eRoles, expectAccessible, signInAs } from './helpers';

/**
 * WP-018 journey: an admin changes something (creates a role), finds the change in Admin › Audit
 * log in plain words, opens the entry, and sees the integrity and archive tabs. The role is
 * deleted at the end (suite-owned data only; the audit entries stay, as they must).
 */
test('audit log: a change shows up as an entry with its chain position', async ({ page }) => {
  await signInAs(page, 'admin', '/admin/roles');
  await deleteE2eRoles(page);
  try {
    const request = page.context().request;
    const me = (await (await request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
    const created = await request.post('/api/v1/roles', {
      data: { name: `E2E audit ${String(Date.now())}`, permissions: [] },
      headers: { 'X-CSRF-Token': me.csrf_token },
    });
    expect(created.status(), await created.text()).toBe(201);

    await page.goto('/admin/audit?action=role.created&range=today');
    const table = page.getByTestId('audit-table');
    await expect(table.getByText('Created a role').first()).toBeVisible();
    await expect(table.getByText('role.created')).toHaveCount(0);
    await expectAccessible(page, 'audit log');

    // Sealing is asynchronous (D-076 item 1): the entry is pending for a moment, then sealed.
    await expect(table.getByText(/^Sealed, position \d+$/).first()).toBeVisible({
      timeout: 15_000,
    });
    await table.locator('[data-testid^="audit-row-"]').first().click();
    const drawer = page.getByTestId('audit-entry-drawer');
    await expect(drawer).toBeVisible();
    await expectAccessible(page, 'audit entry');
    await page.keyboard.press('Escape');

    await page.getByRole('tab', { name: 'Integrity' }).click();
    await expect(page.getByTestId('audit-tabs')).toBeVisible();
    await page.getByRole('tab', { name: 'Archives' }).click();
    await expect(page.getByTestId('audit-archives')).toBeVisible();
    await expectAccessible(page, 'audit archives');
  } finally {
    await deleteE2eRoles(page);
  }
});
