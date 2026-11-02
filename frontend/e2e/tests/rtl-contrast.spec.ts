import { expect, test, type Page } from '@playwright/test';

import { expectTextContrast, resetLanguage, signInAs } from './helpers';

/**
 * WCAG AA text contrast of key screens in Arabic and Urdu. axe skips Arabic-script text (it takes
 * it for an icon ligature), so contrast there is measured from computed colours. The palette
 * itself is covered by theme-contrast.test.ts in packages/ui; this catches a colour used on a
 * real screen. Read-only: it only reads pages.
 */

const SCREENS = ['/', '/incidents', '/dashboards', '/reports', '/admin/users'];

async function language(page: Page, code: 'ar' | 'ur'): Promise<void> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const user = (await (await page.request.get(path)).json()) as { version: number };
  const done = await page.request.patch(path, {
    data: { ui_locale: code },
    headers: { 'If-Match': `"${String(user.version)}"`, 'X-CSRF-Token': me.csrf_token },
  });
  expect(done.status(), await done.text()).toBe(200);
}

for (const code of ['ar', 'ur'] as const) {
  test(`key screens meet WCAG AA text contrast in ${code}`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.emulateMedia({ colorScheme: 'light' });
    await signInAs(page, 'admin');
    await language(page, code);
    try {
      for (const screen of SCREENS) {
        await page.goto(screen);
        await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
        await expect(page.locator('main')).toBeVisible();
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(600); // Ant Design animates colour changes (~0.3 s)
        await expectTextContrast(page, `${screen} (${code})`, { atLeast: 3 });
      }
    } finally {
      await resetLanguage(page);
    }
  });
}
