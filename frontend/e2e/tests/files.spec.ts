import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-022 files end to end with the real ClamAV (D-082 D9), REQ-INC-079:
 * - a file attached to an incident is "Checking for malware", then "Ready", live, with no reload;
 * - an image previews in the browser (AC4) through a short-lived link (AC3);
 * - the EICAR test file is blocked and offers no download (AC1);
 * - a too-large file is refused before it is sent, with the limit (AC2);
 * - the screens are accessible in light, dark, high contrast and Arabic (RTL), and so is
 *   Admin › Files.
 *
 * Suite-owned data only: the incident is "E2E files …"; its files are deleted at the end and the
 * incident goes to the trash (global-teardown removes it).
 */
const SCAN = { timeout: 60_000 };
// The EICAR test file, built here so this source does not trip a developer's virus scanner.
const EICAR = 'X5O!P%@AP[4\\PZX54(P^)7CC)7}$' + 'EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*';
// A 2 x 2 red PNG.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEklEQVR4nGM8ISfHwMDAxAAGAA0EAQijE05aAAAAAElFTkSuQmCC',
  'base64',
);

async function call(page: Page, method: string, path: string, body?: unknown) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  return page.request.fetch(`/api/v1${path}`, {
    method,
    data: body,
    headers: { 'X-CSRF-Token': me.csrf_token },
  });
}

/** The record opens on Conversation (D-081); its files sit with the description, on Details. */
async function openDetails(page: Page, id: string): Promise<void> {
  await page.goto(`/incidents/${id}`);
  await page.getByRole('tab', { name: /^(Details|التفاصيل)$/ }).click();
}

async function attach(page: Page, name: string, mimeType: string, buffer: Buffer): Promise<void> {
  await page
    .getByTestId('inc-attachments-drop')
    .locator('input[type="file"]')
    .setInputFiles({ name, mimeType, buffer });
}

test('files: checked live, previewed, malware blocked, accessible in every theme and Arabic', async ({
  page,
}) => {
  test.setTimeout(240_000);
  await signInAs(page, 'admin', '/incidents');
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { user: { id: string } };
  const created = await call(page, 'POST', '/incidents', {
    subject: `E2E files ${String(Date.now()).slice(-7)}`,
    requester_id: me.user.id,
  });
  expect(created.status(), await created.text()).toBe(201);
  const item = (await created.json()) as { id: string; version: number };
  try {
    await openDetails(page, item.id);
    const files = page.getByTestId('inc-attachments');
    await expect(files).toBeVisible();

    // A text file: checked by ClamAV, then ready, without a reload (realtime files.changed).
    await attach(page, 'notes.txt', 'text/plain', Buffer.from('Printer logs\n'.repeat(200)));
    await expect(files.getByText('notes.txt')).toBeVisible();
    await expect(files.getByRole('button', { name: 'Download: notes.txt' })).toBeVisible(SCAN);

    // An image previews in the browser.
    await attach(page, 'screenshot.png', 'image/png', PNG);
    const preview = files.getByRole('button', { name: 'Preview: screenshot.png' });
    await expect(preview).toBeVisible(SCAN);
    await preview.click();
    await expect(page.getByTestId('file-preview-image')).toBeVisible();
    await expectAccessible(page, 'file preview');
    await page.keyboard.press('Escape');

    // Malware is blocked for good: no preview, no download.
    await attach(page, 'eicar.txt', 'text/plain', Buffer.from(EICAR));
    await expect(files.getByText('Blocked: malware found')).toBeVisible(SCAN);
    await expect(files.getByRole('button', { name: 'Download: eicar.txt' })).toHaveCount(0);

    // Too large for the tenant's limit (25 MB): refused before sending, with the limit.
    await attach(page, 'video.mp4', 'video/mp4', Buffer.alloc(25_000_001));
    await expect(files.getByRole('alert')).toHaveText(
      'video.mp4 is larger than the limit of 25 MB.',
    );

    for (const theme of ['light', 'dark', 'high_contrast'] as const) {
      await page.evaluate((value) => {
        window.localStorage.setItem('supportx.theme_mode', value);
      }, theme);
      await openDetails(page, item.id);
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await expect(files.getByText('notes.txt')).toBeVisible();
      await expectAccessible(page, `incident with files (${theme})`);
      await page.goto('/admin/files');
      await expect(page.getByTestId('admin-files')).toBeVisible();
      await expect(page.getByRole('spinbutton', { name: /MB/ })).toBeVisible();
      await expectAccessible(page, `Admin › Files (${theme})`);
    }
    await page.evaluate(() => {
      window.localStorage.setItem('supportx.theme_mode', 'light');
    });
    await openDetails(page, item.id);
    await page.getByTestId('appearance-menu').click();
    await page.getByTestId('language-select').click();
    await page.locator('.ant-select-item-option[title="العربية"]').click();
    await page.getByTestId('appearance-menu').click();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(files.getByText('محظور: عُثر على برنامج ضار')).toBeVisible();
    await expectAccessible(page, 'incident with files (Arabic, RTL)');
  } finally {
    await resetLanguage(page);
    const listed = await call(page, 'GET', `/files/records/incident/${item.id}`);
    if (listed.ok()) {
      for (const file of (await listed.json()) as { id: string }[]) {
        await call(page, 'DELETE', `/files/${file.id}`);
      }
    }
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
});
