import { expect, test, type Browser, type Page } from '@playwright/test';

import { PORTAL_URL, SEEDED } from '../stack';
import { expectAccessible, signIn, signInAs } from './helpers';

/**
 * Branding (docs/architecture/branding.md): the SupportX logo and colours on the Keycloak login
 * page, the console, the portal and the About dialog, in the version each theme needs, with
 * favicons and the web manifest served, and axe clean in light, dark, high contrast and Arabic.
 * Read-only: nothing is created or changed.
 */

type Mode = 'light' | 'dark' | 'high_contrast';
const MODES: Mode[] = ['light', 'dark', 'high_contrast'];
/** The full-logo file each theme shows (all above Vite's inline limit, so named in builds too). */
const LOGO_FILE: Record<Mode, string> = {
  light: 'logo-dark-text',
  dark: 'logo-white-text',
  high_contrast: 'logo-high-contrast',
};

async function applyTheme(page: Page, mode: Mode): Promise<void> {
  await page.evaluate((value) => {
    window.localStorage.setItem('supportx.theme_mode', value);
  }, mode);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', mode);
}

/** The visible header logo has loaded (a broken file would have no natural size). */
async function expectHeaderLogo(page: Page, mode: Mode): Promise<void> {
  const logo = page.getByRole('banner').getByTestId('brand-logo-full');
  await expect(logo).toBeVisible();
  await expect(logo).toHaveAttribute('alt', 'SupportX');
  await expect(logo).toHaveAttribute('src', new RegExp(LOGO_FILE[mode]));
  await expect
    .poll(() => logo.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
}

async function openAbout(page: Page, label: string): Promise<void> {
  await page.getByTestId('user-menu').click();
  await page.getByRole('menuitem', { name: label }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId('brand-logo-full')).toBeVisible();
}

test('login page: SupportX logo and colours, accessible in light, dark, high contrast and Arabic', async ({
  browser,
}) => {
  const variants: { name: string; options: Parameters<Browser['newContext']>[0]; logo: string }[] =
    [
      { name: 'light', options: { colorScheme: 'light' }, logo: LOGO_FILE.light },
      { name: 'dark', options: { colorScheme: 'dark' }, logo: LOGO_FILE.dark },
      {
        name: 'high contrast',
        options: { colorScheme: 'light', contrast: 'more' },
        logo: LOGO_FILE.high_contrast,
      },
      { name: 'Arabic', options: { colorScheme: 'light', locale: 'ar' }, logo: LOGO_FILE.light },
    ];
  for (const variant of variants) {
    const context = await browser.newContext(variant.options);
    const page = await context.newPage();
    try {
      await page.goto('/');
      await expect(page).toHaveURL(/\/realms\/supportx\/protocol\/openid-connect\/auth/);
      await expect(page.locator('#username')).toBeVisible();
      const header = page.locator('#kc-header-wrapper');
      await expect
        .poll(() => header.evaluate((node) => getComputedStyle(node).backgroundImage))
        .toContain(variant.logo);
      if (variant.name === 'Arabic') {
        await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
      }
      await expectAccessible(page, `login page (${variant.name})`);
    } finally {
      await context.close();
    }
  }
});

test('console: favicons and manifest served, the logo and About dialog in every theme', async ({
  page,
}) => {
  await signInAs(page, 'tech');
  const request = page.context().request;
  for (const path of ['/favicon.ico', '/apple-touch-icon.png', '/icon-192.png', '/icon-512.png']) {
    const response = await request.get(path);
    expect(response.status(), path).toBe(200);
    expect(response.headers()['content-type'], path).toMatch(/^image\//);
  }
  const manifest = await request.get('/site.webmanifest');
  expect(manifest.status()).toBe(200);
  expect(((await manifest.json()) as { name: string }).name).toBe('SupportX');
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', /favicon\.ico$/);

  for (const mode of MODES) {
    await applyTheme(page, mode);
    await expectHeaderLogo(page, mode);
    await expectAccessible(page, `console with logo (${mode})`);
    await openAbout(page, 'About SupportX');
    await expect(page.getByTestId('about-version')).toHaveText(/^Version \S+$/);
    await expectAccessible(page, `about dialog (${mode})`);
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  }
  await applyTheme(page, 'light');
});

test('portal: logo and welcome band, accessible in every theme, right-to-left in Arabic', async ({
  browser,
}) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    // The seeded requester reads the portal in Arabic.
    await signIn(page, SEEDED.arabic.email, SEEDED.arabic.password, `${PORTAL_URL}/`);
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    for (const mode of MODES) {
      await applyTheme(page, mode);
      await expectHeaderLogo(page, mode);
      await expect(page.getByTestId('portal-welcome')).toBeVisible();
      await expectAccessible(page, `portal home (${mode}, Arabic)`);
    }
    await openAbout(page, 'حول SupportX');
    await expect(page.getByTestId('about-version')).toHaveText(/^الإصدار \S+$/);
    await expectAccessible(page, 'portal about dialog (Arabic)');
    await page.keyboard.press('Escape');
    await applyTheme(page, 'light');
  } finally {
    await context.close();
  }
});
