import { expect, test } from '@playwright/test';

import { devSubscription, SEEDED } from '../stack';
import { signIn } from './helpers';

// Other Company's plan is changed with the documented dev tool and always restored afterwards.
test.afterAll(() => {
  devSubscription('other', '--expires never --status active --technicians 2');
});

test('read-only mode: persistent banner, edit buttons disabled, reads still work', async ({
  page,
}) => {
  devSubscription('other', '--expires 2026-09-01');
  await signIn(page, SEEDED.other.email, SEEDED.other.password, '/profile');
  // The plan change reaches the API through the event bus and cache invalidation (WP-009).
  await expect(async () => {
    await page.reload();
    await expect(page.getByTestId('read-only-banner')).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await expect(page.getByTestId('read-only-banner')).toContainText(
    'Read-only mode: you can view and export data.',
  );
  await expect(page.getByTestId('read-only-banner')).toContainText(
    'The licence or subscription has expired.',
  );
  await expect(page.getByTestId('profile-save')).toBeDisabled();
  await page.getByTestId('read-only-action').first().hover();
  await expect(page.getByText(/Not available in read-only mode/)).toBeVisible();
  await expect(page.getByTestId('profile-signature')).toBeVisible(); // data still readable
  await page.screenshot({ path: 'test-results/read-only.png', fullPage: true });

  devSubscription('other', '--expires never');
  await expect(async () => {
    await page.reload();
    await expect(page.getByTestId('profile-save')).toBeEnabled({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await expect(page.getByTestId('read-only-banner')).toHaveCount(0);
});
