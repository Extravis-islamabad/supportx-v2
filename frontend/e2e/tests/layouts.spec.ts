import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, goToSection, mainNav, navItems, signInAs } from './helpers';

/**
 * Navigation layouts (WP-011): top bar (default), side bar, compact side bar. The choice is a
 * server-side user preference: it survives a reload and follows the user to another session,
 * live. Menus are the same in every layout; every layout passes axe in light, dark, high
 * contrast and Arabic (RTL). The suite user is put back on the top bar at the end.
 */

const LAYOUTS = [
  { code: 'top', label: 'Top bar', nav: 'nav-top' },
  { code: 'side', label: 'Side bar', nav: 'nav-side' },
  { code: 'side_compact', label: 'Compact side bar', nav: 'nav-compact' },
] as const;

/** Do something in the Appearance popover, then close it (it toggles; Escape does not). */
async function inAppearance(page: Page, action: () => Promise<void>): Promise<void> {
  const panel = page.getByTestId('nav-layout');
  if (!(await panel.isVisible())) await page.getByTestId('appearance-menu').click();
  await expect(panel).toBeVisible();
  await action();
  if (await panel.isVisible()) await page.getByTestId('appearance-menu').click();
  await expect(panel).toBeHidden();
}

async function chooseLayout(page: Page, label: string): Promise<void> {
  await inAppearance(page, async () => {
    await page.getByTestId('nav-layout').getByText(label, { exact: true }).click();
  });
}

/** Theme through its stored preference (the picker itself is covered by shell.spec.ts). */
async function applyTheme(page: Page, mode: 'light' | 'dark' | 'high_contrast'): Promise<void> {
  await page.evaluate((value) => {
    window.localStorage.setItem('supportx.theme_mode', value);
  }, mode);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', mode);
}

test('three layouts: same menus, persisted server-side, live on another session, accessible', async ({
  browser,
}) => {
  test.setTimeout(180_000); // three layouts × three themes + Arabic, each scanned by axe
  const contextA = await browser.newContext();
  const contextB = await browser.newContext();
  const a = await contextA.newPage();
  const b = await contextB.newPage();
  await signInAs(a, 'tech');
  await signInAs(b, 'tech');
  await expect(b.locator('html')).toHaveAttribute('data-realtime-status', 'connected');
  const expected = await navItems(a);
  try {
    for (const layout of LAYOUTS) {
      await chooseLayout(a, layout.label);
      await expect(a.getByTestId(layout.nav)).toBeVisible();
      expect(await navItems(a)).toEqual(expected); // permission-driven items, same everywhere
      // The other session follows live (its own channel tells it the profile changed).
      await expect(b.getByTestId(layout.nav)).toBeVisible({ timeout: 5_000 });
      // A reload keeps it: the choice is stored on the server, not in the browser.
      await a.reload();
      await expect(a.getByTestId(layout.nav)).toBeVisible();
      await goToSection(a, 'Knowledge');
      await expect(a.getByRole('heading', { name: 'Knowledge', level: 1 })).toBeVisible();

      for (const theme of ['light', 'dark', 'high_contrast'] as const) {
        await applyTheme(a, theme);
        await expect(a.getByTestId(layout.nav)).toBeVisible();
        await expectAccessible(a, `${layout.code} layout, ${theme}`);
      }
      await applyTheme(a, 'light');
      await a.screenshot({ path: `test-results/layout-${layout.code}.png` });
    }

    // RTL: the side bars sit on the right, the top bar starts on the right.
    await inAppearance(a, async () => {
      await a.getByTestId('language-select').click();
      await a.locator('.ant-select-item-option[title="العربية"]').click();
    });
    await expect(a.locator('html')).toHaveAttribute('dir', 'rtl');
    const width = a.viewportSize()?.width ?? 0;
    const sider = await a.locator('.ant-layout-sider').boundingBox();
    expect(sider?.x ?? 0).toBeGreaterThan(width / 2);
    await expectAccessible(a, 'compact side bar, Arabic');
    await chooseLayout(a, 'شريط علوي');
    await expect(a.getByTestId('nav-top')).toBeVisible();
    const first = await mainNav(a).locator('li[role="menuitem"]').first().boundingBox();
    expect(first?.x ?? 0).toBeGreaterThan(width / 2);
    await expectAccessible(a, 'top bar, Arabic');
    await a.screenshot({ path: 'test-results/layout-top-ar.png' });
  } finally {
    // Back to the default for the rest of the suite (and in English, which is not stored).
    await chooseLayout(a, 'شريط علوي').catch(() => undefined);
    await contextA.close();
    await contextB.close();
  }
});
