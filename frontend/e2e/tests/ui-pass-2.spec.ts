import { mkdirSync } from 'node:fs';

import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, expectTextContrast, signInAs } from './helpers';

// UI pass 2 (docs/design/target): the incident list, an incident record and the dashboard in
// each navigation layout, in English and Arabic (RTL), and the side bar at 390 px. Every view
// is saved as a full-page screenshot (the PR's before and after, uploaded by the stack smoke as
// `ui-screens`), then checked with axe; Arabic text contrast is measured directly, as axe skips
// it. Kept as pass 2's regression check.

const SCREENS = 'ui-screens';
const LAYOUTS = ['side', 'side_compact', 'top'] as const;
type Layout = (typeof LAYOUTS)[number];

interface Me {
  csrf_token: string;
  user: { id: string };
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

/** Save the person's own preferences through the API (If-Match, CSRF). */
async function save(page: Page, data: Record<string, string | null>): Promise<void> {
  const { csrf_token, user } = await me(page);
  const path = `/api/v1/users/${user.id}`;
  const read = (await (await page.request.get(path)).json()) as { version: number };
  const saved = await page.request.patch(path, {
    data,
    headers: { 'If-Match': `"${String(read.version)}"`, 'X-CSRF-Token': csrf_token },
  });
  expect(saved.status(), await saved.text()).toBe(200);
}

async function shoot(page: Page, name: string): Promise<void> {
  await page.waitForTimeout(600); // let Ant Design's colour transitions settle
  const body = await page.screenshot({ path: `${SCREENS}/${name}.png`, fullPage: true });
  await test.info().attach(name, { body, contentType: 'image/png' });
}

test('UI pass 2: list, record and dashboard in every layout, English and Arabic, and 390 px', async ({
  page,
}) => {
  test.setTimeout(600_000);
  mkdirSync(SCREENS, { recursive: true });
  await signInAs(page, 'admin', '/incidents');
  const { csrf_token, user } = await me(page);
  const before = (await (await page.request.get(`/api/v1/users/${user.id}`)).json()) as {
    nav_layout: string;
  };
  const made = await page.request.post('/api/v1/incidents', {
    data: {
      subject: `E2E UI pass 2 ${String(Date.now())}`,
      requester_id: user.id,
      description: '<p>The VPN disconnects every ten minutes.</p>',
    },
    headers: { 'X-CSRF-Token': csrf_token },
  });
  expect(made.status(), await made.text()).toBe(201);
  const incident = ((await made.json()) as { id: string }).id;

  const views = [
    { key: 'list', path: '/incidents' },
    { key: 'record', path: `/incidents/${incident}` },
    { key: 'dashboard', path: '/' },
  ];
  const run = async (
    layout: Layout,
    locale: 'en' | 'ar',
    width: number,
    theme: 'light' | 'dark' = 'light',
  ) => {
    await save(page, { nav_layout: layout, ui_locale: locale });
    await page.setViewportSize({ width, height: 900 });
    // The theme this browser remembers (it wins as a page opens).
    await page.evaluate((mode) => {
      window.localStorage.setItem('supportx.theme_mode', mode);
    }, theme);
    for (const view of views) {
      await page.goto(view.path);
      await expect(page.locator('html')).toHaveAttribute('dir', locale === 'ar' ? 'rtl' : 'ltr');
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(page.locator('main').first()).toBeVisible();
      const name = `${view.key}-${layout}-${locale}-${String(width)}${theme === 'dark' ? '-dark' : ''}`;
      await shoot(page, name);
      // Soft: every view is still photographed when one has a finding.
      await expect.soft(async () => expectAccessible(page, name)).toPass({ timeout: 30_000 });
      if (locale === 'ar') {
        await expect.soft(async () => expectTextContrast(page, name)).toPass({ timeout: 30_000 });
      }
    }
  };
  try {
    for (const layout of LAYOUTS) {
      for (const locale of ['en', 'ar'] as const) await run(layout, locale, 1440);
    }
    for (const locale of ['en', 'ar'] as const) await run('side', locale, 390);
    // Dark: the timeline, counters and tiles keep the theme's colours (lane A's review), measured.
    for (const locale of ['en', 'ar'] as const) await run('side', locale, 1440, 'dark');
  } finally {
    await save(page, { nav_layout: before.nav_layout, ui_locale: null });
    await page.evaluate(() => {
      window.localStorage.removeItem('supportx.theme_mode');
    });
    const found = await page.request.get(`/api/v1/incidents/${incident}`);
    if (found.status() === 200) {
      const { version } = (await found.json()) as { version: number };
      await page.request.delete(`/api/v1/incidents/${incident}`, {
        headers: { 'If-Match': `"${String(version)}"`, 'X-CSRF-Token': csrf_token },
      });
    }
  }
});

test('a message starts below the header, never over its search field, in Arabic and at 390 px', async ({
  page,
}) => {
  await signInAs(page, 'tech', '/profile');
  try {
    for (const [locale, width] of [
      ['ar', 1440],
      ['ar', 390],
      ['en', 390],
    ] as const) {
      await save(page, { ui_locale: locale });
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/profile');
      await expect(page.locator('html')).toHaveAttribute('dir', locale === 'ar' ? 'rtl' : 'ltr');
      await page.getByTestId('profile-save').click();
      const notice = page.locator('.ant-message-notice').first();
      await expect(notice).toBeVisible();
      const header = await page.getByRole('banner').boundingBox();
      const box = await notice.boundingBox();
      expect(header, 'header').not.toBeNull();
      expect(box, 'message').not.toBeNull();
      // Its top edge is at or under the header's bottom edge.
      expect(
        (box?.y ?? 0) + 1,
        `message below the header (${locale}, ${String(width)} px)`,
      ).toBeGreaterThanOrEqual((header?.y ?? 0) + (header?.height ?? 0));
      await expect(page.locator('.ant-message-notice')).toHaveCount(0, { timeout: 10_000 });
    }
  } finally {
    await save(page, { ui_locale: null });
  }
});
