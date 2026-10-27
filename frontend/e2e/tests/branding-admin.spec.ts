import { expect, test } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

/**
 * WP-017-FIX (QA of WP-017): Admin › Branding is axe clean in light, dark and high contrast with
 * the contrast checks on screen (BUG-04: the readable and failing tags), the empty list of
 * custom domains (BUG-05) and the image cards without uploads (BUG-06: the dark-logo card).
 * Read-only: a colour is typed but never saved.
 */
test('BUG-04 BUG-05 BUG-06: the branding screen is readable in every theme', async ({ page }) => {
  await signInAs(page, 'admin', '/admin/branding');
  for (const theme of ['light', 'dark', 'high_contrast'] as const) {
    await page.evaluate((value) => {
      window.localStorage.setItem('supportx.theme_mode', value);
    }, theme);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
    await expect(page.getByTestId('admin-branding')).toBeVisible();
    await expect(page.getByTestId('branding-domains')).toBeVisible();
    const checks = page.getByTestId('branding-checks');
    // A readable colour: every tag "Readable", the whole screen (preview included) is clean.
    await page.getByTestId('branding-primary-input').fill('#0b5394');
    await expect(checks.getByText('Readable').first()).toBeVisible();
    await expectAccessible(page, `Admin › Branding, readable colour (${theme})`);
    // A faint one: "Too faint" tags and the alert are readable. The preview draws the refused
    // colour on purpose (to show why it is refused), so it is left out of this scan only.
    await page.getByTestId('branding-primary-input').fill('#1e90ff');
    await expect(checks.getByText('Too faint').first()).toBeVisible();
    await expectAccessible(page, `Admin › Branding, faint colour (${theme})`, {
      exclude: '[data-testid="branding-preview"]',
    });
  }
  await page.evaluate(() => {
    window.localStorage.setItem('supportx.theme_mode', 'light');
  });
});
