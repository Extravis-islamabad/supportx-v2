import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-027 search (REQ-INC-085, ADR-029) end to end, on the real database:
 * - Ctrl+K finds an incident by a different Arabic word form, without diacritics, and by a
 *   misspelt English word, and opens it;
 * - the incident just opened is offered as recently viewed;
 * - the palette is accessible in light, dark and Arabic (RTL).
 *
 * Suite-owned data only: the incidents are "E2E search …" and are moved to the trash at the end.
 */
async function call(page: Page, method: string, path: string, body?: unknown) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  return page.request.fetch(`/api/v1${path}`, {
    method,
    data: body,
    headers: { 'X-CSRF-Token': me.csrf_token },
  });
}

async function palette(page: Page, typed: string) {
  await page.keyboard.press('Control+k');
  const input = page.getByRole('combobox', { name: 'Type a page name…' });
  await expect(input).toBeVisible();
  await input.fill(typed);
  return page.getByRole('dialog');
}

test('search: Arabic word forms, typos and recent incidents in Ctrl+K, accessible', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await signInAs(page, 'admin', '/incidents');
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { user: { id: string } };
  const tag = String(Date.now()).slice(-7);
  const made: { id: string; version: number; display_id: string }[] = [];
  for (const subject of [`E2E search ${tag} الطابعات لا تعمل`, `E2E search ${tag} Printer jams`]) {
    const created = await call(page, 'POST', '/incidents', { subject, requester_id: me.user.id });
    expect(created.status(), await created.text()).toBe(201);
    made.push((await created.json()) as { id: string; version: number; display_id: string });
  }
  const [arabic, printer] = made as [(typeof made)[number], (typeof made)[number]];
  try {
    await page.goto('/');
    // Another word form, with diacritics typed: the record still comes first.
    let dialog = await palette(page, `${tag} طَابِعَة`);
    const found = dialog.getByTestId(`palette-incident-${arabic.display_id}`);
    await expect(found).toBeVisible();
    await expectAccessible(page, 'command palette with results (light)');
    await found.click();
    await expect(page).toHaveURL(new RegExp(`/incidents/${arabic.id}`));

    // A typo finds the printer; the incident just opened is offered as recently viewed.
    dialog = await palette(page, `${tag} printr`);
    await expect(dialog.getByTestId(`palette-incident-${printer.display_id}`)).toBeVisible();
    await page.getByRole('combobox', { name: 'Type a page name…' }).fill('');
    await expect(dialog.getByText('Recently viewed')).toBeVisible();
    await expect(dialog.getByTestId(`palette-incident-${arabic.display_id}`)).toBeVisible();
    await page.keyboard.press('Escape');

    for (const theme of ['dark', 'high_contrast'] as const) {
      await page.evaluate((value) => {
        window.localStorage.setItem('supportx.theme_mode', value);
      }, theme);
      await page.goto('/');
      await palette(page, `${tag} printer`);
      await expect(page.getByTestId(`palette-incident-${printer.display_id}`)).toBeVisible();
      await expectAccessible(page, `command palette with results (${theme})`);
      await page.keyboard.press('Escape');
    }
    await page.evaluate(() => {
      window.localStorage.setItem('supportx.theme_mode', 'light');
    });
    await page.goto('/');
    await page.getByTestId('appearance-menu').click();
    await page.getByTestId('language-select').click();
    await page.locator('.ant-select-item-option[title="العربية"]').click();
    await page.getByTestId('appearance-menu').click();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await palette(page, `${tag} الطابعة`);
    await expect(page.getByTestId(`palette-incident-${arabic.display_id}`)).toBeVisible();
    await expect(page.getByText('الحوادث', { exact: true }).last()).toBeVisible();
    await expectAccessible(page, 'command palette with results (Arabic, RTL)');
    await page.keyboard.press('Escape');
  } finally {
    await resetLanguage(page);
    for (const item of made) {
      const fresh = (await (await call(page, 'GET', `/incidents/${item.id}`)).json()) as {
        version: number;
      };
      await page.request.fetch(`/api/v1/incidents/${item.id}`, {
        method: 'DELETE',
        headers: {
          'X-CSRF-Token': (
            (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string }
          ).csrf_token,
          'If-Match': `"${String(fresh.version)}"`,
        },
      });
    }
  }
});
