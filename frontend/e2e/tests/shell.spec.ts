import { expect, test } from '@playwright/test';

import { SEEDED } from '../stack';
import { expectAccessible, goToSection, navItems, settledBox, signIn, signInAs } from './helpers';

const SECTIONS = [
  'Service requests',
  'Problems',
  'Changes',
  'Releases',
  'Assets',
  'CMDB',
  'Knowledge',
];

test('navigation: every section opens a translated coming-soon page; palette and 404 work', async ({
  page,
}) => {
  await signInAs(page, 'tech');
  for (const section of SECTIONS) {
    await goToSection(page, section);
    await expect(page.getByRole('heading', { name: section, level: 1 })).toBeVisible();
    await expect(page.getByText(/being built/)).toBeVisible();
  }
  expect(await navItems(page)).not.toContain('admin'); // not a tenant admin

  // Reports is a real page (WP-035), not a coming-soon one.
  await goToSection(page, 'Reports');
  await expect(page.getByRole('heading', { name: 'Reports', level: 1 })).toBeVisible();
  await expect(page.getByTestId('reports-search')).toBeVisible();
  await expect(page.getByText(/being built/)).toHaveCount(0);
  await expectAccessible(page, 'reports home');

  await page.keyboard.press('Control+k');
  const palette = page.getByRole('combobox', { name: 'Type a page name…' });
  await palette.fill('know');
  await palette.press('Enter');
  await expect(page).toHaveURL(/\/knowledge$/);

  await page.goto('/no/such/page');
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  await page.screenshot({ path: 'test-results/shell-navigation.png', fullPage: true });
});

test('theme: light, dark and high contrast apply to the whole page', async ({ page }) => {
  await signInAs(page, 'tech');
  const background = () =>
    page.evaluate(
      () =>
        getComputedStyle(document.querySelector('.ant-layout') ?? document.body).backgroundColor,
    );
  await page.getByTestId('appearance-menu').click();
  await page.getByText('Light', { exact: true }).click();
  const light = await background();
  await page.getByText('Dark', { exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await background()).not.toBe(light);
  await page.screenshot({ path: 'test-results/theme-dark.png' });
  await page.getByText('High contrast', { exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'high_contrast');
  await page.keyboard.press('Escape');
  await expectAccessible(page, 'home (high contrast)');
  await page.screenshot({ path: 'test-results/theme-high-contrast.png' });
  // The choice is remembered for the next visit.
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'high_contrast');
  // Each test runs in a fresh browser context, so the remembered theme does not leak.
});

test('RTL: the Arabic user gets Arabic labels right-to-left', async ({ page }) => {
  await signIn(page, SEEDED.arabic.email, SEEDED.arabic.password);
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
  const nav = page.getByRole('navigation', { name: 'التنقل الرئيسي' });
  const home = nav.getByText('الرئيسية', { exact: true }).filter({ visible: true });
  await expect(home).toBeVisible();
  // The top bar starts on the right in RTL (the side bar layouts: see layouts.spec.ts).
  const box = await settledBox(home);
  const width = page.viewportSize()?.width ?? 0;
  expect(box?.x ?? 0).toBeGreaterThan(width / 2);
  await expectAccessible(page, 'home (Arabic, RTL)');
  await page.screenshot({ path: 'test-results/rtl-arabic.png' });
});

test('accessibility: main screens have no serious or critical axe violations', async ({ page }) => {
  await signInAs(page, 'admin');
  await expectAccessible(page, 'home');
  await page.goto('/problems');
  await expect(page.getByRole('heading', { name: 'Problems' })).toBeVisible();
  await expectAccessible(page, 'coming soon');
  await page.goto('/admin/users');
  await expect(page.getByTestId('users-table').getByText('E2E Scroll 00')).toBeVisible();
  await expectAccessible(page, 'users');
  await page.goto('/profile');
  await expect(page.getByTestId('profile-signature')).toBeVisible();
  await expectAccessible(page, 'my profile');
  await page.getByTestId('appearance-menu').click();
  await page.getByText('Dark', { exact: true }).click();
  await page.keyboard.press('Escape');
  await expectAccessible(page, 'my profile (dark)');
});

test('where you are: breadcrumbs and the tab title, never "Technician Console", Arabic and 390 px', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signInAs(page, 'admin', '/reports/builtin/incidents_open_by_priority');
  const crumbs = page.getByTestId('header-crumbs');
  await expect(crumbs).toHaveText('Reports/Open incidents by priority');
  await expect(crumbs.getByRole('link', { name: 'Reports' })).toHaveAttribute('href', '/reports');
  await expect(page).toHaveTitle('Open incidents by priority · Reports · SupportX');
  await expect(page.getByText('Technician Console')).toHaveCount(0);

  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const setLocale = async (ui_locale: string | null) => {
    const user = (await (await page.request.get(path)).json()) as { version: number };
    const saved = await page.request.patch(path, {
      data: { ui_locale },
      headers: { 'If-Match': `"${String(user.version)}"`, 'X-CSRF-Token': me.csrf_token },
    });
    expect(saved.status(), await saved.text()).toBe(200);
  };
  try {
    await setLocale('ar');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(crumbs).toHaveText('التقارير/الحوادث المفتوحة حسب الأولوية');
    await expect(page).toHaveTitle('الحوادث المفتوحة حسب الأولوية · التقارير · SupportX');
    for (const width of [1280, 390]) {
      await page.setViewportSize({ width, height: 800 });
      await expect(crumbs).toBeVisible();
      const sideways = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(sideways, `no sideways scroll at ${String(width)} px`).toBeLessThanOrEqual(0);
    }
    await expectAccessible(page, 'report page with breadcrumbs (Arabic)');
  } finally {
    await setLocale(null);
  }
});
