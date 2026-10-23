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
  await signIn(page, SEEDED.other.email, SEEDED.other.password, '/profile');
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected');
  // The plan change reaches the open page live: event bus → fan-out → banner (WP-009, WP-011).
  devSubscription('other', '--expires 2026-09-01');
  await expect(page.getByTestId('read-only-banner')).toBeVisible({ timeout: 5_000 });
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
  // Back to normal without a reload either.
  await expect(page.getByTestId('profile-save')).toBeEnabled({ timeout: 5_000 });
  await expect(page.getByTestId('read-only-banner')).toHaveCount(0);
});
