import { expect, test, type Page } from '@playwright/test';

import { expectToastsAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WCAG AA contrast of toasts (success, error, warning, info), left to right and right to left.
 * The other axe checks wait until toasts have gone (they fade during a scan), so this one holds
 * them open on the dev page and measures them fully shown. Light mode is set, not assumed.
 */

async function arabic(page: Page): Promise<void> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const user = (await (await page.request.get(path)).json()) as { version: number };
  const done = await page.request.patch(path, {
    data: { ui_locale: 'ar' },
    headers: { 'If-Match': `"${String(user.version)}"`, 'X-CSRF-Token': me.csrf_token },
  });
  expect(done.status(), await done.text()).toBe(200);
}

async function showToasts(page: Page): Promise<void> {
  await page.goto('/dev/components');
  const button = page.getByTestId('dev-toasts');
  // The component page exists only in dev builds (`import.meta.env.DEV`, router.tsx): the k3d
  // nightly serves production bundles, which leave it out. Stack-smoke runs this against the dev
  // servers, so the check still runs on every full-ci PR and every night.
  const shown = await button.waitFor({ timeout: 15_000 }).then(
    () => true,
    () => false,
  );
  test.skip(!shown, 'the dev component page exists only in dev builds (stack-smoke runs this)');
  await button.click();
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await signInAs(page, 'admin');
});

test('toasts meet WCAG AA contrast, left to right', async ({ page }) => {
  await showToasts(page);
  await expect(page.locator('html')).toHaveAttribute('dir', 'ltr');
  await expectToastsAccessible(page, 'toasts (English)');
});

test('toasts meet WCAG AA contrast, right to left', async ({ page }) => {
  await arabic(page);
  try {
    await showToasts(page);
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expectToastsAccessible(page, 'toasts (Arabic)');
  } finally {
    await resetLanguage(page);
  }
});
