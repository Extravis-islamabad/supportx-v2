import { expect, test } from '@playwright/test';

import { openSelect, resetPreferences, signInAs } from './helpers';

// WP-042 (REQ-ADM-058 AC2, REQ-ADM-062): preferences live on the server, so a theme or text
// size chosen in one browser changes every other open browser of the same person, within two
// seconds, with no reload. The person is put back on the defaults afterwards.

test('theme and text size follow the person to another open browser within 2 s', async ({
  browser,
}) => {
  const first = await browser.newContext();
  const second = await browser.newContext();
  const a = await first.newPage();
  const b = await second.newPage();
  try {
    await signInAs(a, 'tech', '/profile');
    await signInAs(b, 'tech', '/');
    const card = a.getByTestId('preferences');

    await card.getByTestId('pref-theme').getByText('Dark', { exact: true }).click();
    await expect(a.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(b.locator('html')).toHaveAttribute('data-theme', 'dark', { timeout: 2_000 });

    await openSelect(a, 'pref-text-scale');
    await a.getByTitle('130%', { exact: true }).click();
    await expect(b.locator('html')).toHaveAttribute('data-text-scale', '130', { timeout: 2_000 });

    // Back to light and 100 %, applied in both.
    await card.getByTestId('pref-theme').getByText('Light', { exact: true }).click();
    await openSelect(a, 'pref-text-scale');
    await a.getByTitle('100%', { exact: true }).click();
    await expect(b.locator('html')).toHaveAttribute('data-theme', 'light', { timeout: 2_000 });
    await expect(b.locator('html')).toHaveAttribute('data-text-scale', '100', { timeout: 2_000 });
  } finally {
    await resetPreferences(a);
    await first.close();
    await second.close();
  }
});
