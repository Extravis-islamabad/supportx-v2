import { expect, test, type Browser, type Page } from '@playwright/test';

import { renameSuiteUser, USERS } from '../stack';
import { deleteE2eRoles, signInAs } from './helpers';

/**
 * WP-011 journeys with two browsers side by side: a change in one shows in the other with no
 * reload (architecture.md §8). Suite-owned users and roles only; everything changed is put back.
 */

const LIVE = { timeout: 5_000 };

async function open(browser: Browser, user: 'tech' | 'admin' | 'limited', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

async function csrf(page: Page): Promise<string> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  return me.csrf_token;
}

test("users list: another user's change appears in the admin's list without a reload", async ({
  browser,
}) => {
  const admin = await open(browser, 'admin', '/admin/users');
  const live = `E2E Live ${String(Date.now()).slice(-6)}`;
  try {
    await admin.page
      .getByRole('searchbox', { name: 'Search by name or email' })
      .fill('e2e.limited');
    await expect(admin.page.getByText('Lina E2E Limited')).toBeVisible();

    // The user's name changes in Keycloak and syncs to SupportX at their next sign-in.
    await renameSuiteUser('limited', live);
    const user = await open(browser, 'limited', '/');
    await expect(admin.page.getByText(`Lina ${live}`)).toBeVisible(LIVE);
    await user.context.close();
  } finally {
    await renameSuiteUser('limited', USERS.limited.last);
    const restore = await open(browser, 'limited', '/'); // syncs the name back
    await restore.context.close();
    await expect(admin.page.getByText('Lina E2E Limited')).toBeVisible(LIVE);
    await admin.context.close();
  }
});

test('profile: a save in another window is announced before you save, with presence', async ({
  browser,
}) => {
  const first = await open(browser, 'tech', '/profile');
  const second = await open(browser, 'tech', '/profile');
  const signature = first.page.getByTestId('profile-signature');
  const original = await signature.inputValue();
  try {
    // Each window sees the other one.
    await expect(first.page.getByTestId('presence')).toHaveAttribute(
      'aria-label',
      'Also viewing: You (another window)',
      LIVE,
    );
    const value = `Live ${String(Date.now())}`;
    await second.page.getByTestId('profile-signature').fill(value);
    await second.page.getByTestId('profile-save').click();
    await expect(second.page.getByText('Your preferences were saved.')).toBeVisible();

    const notice = first.page.getByTestId('live-change-notice');
    await expect(notice).toContainText(
      'This record was just changed by Erin E2E Tech (you, in another window).',
      LIVE,
    );
    await first.page.getByTestId('live-change-reload').click();
    await expect(signature).toHaveValue(value);
    await expect(notice).toHaveCount(0);
  } finally {
    await signature.fill(original);
    await first.page.getByTestId('profile-save').click();
    await expect(first.page.getByText('Your preferences were saved.')).toBeVisible();
    await first.context.close();
    await second.context.close();
  }
});

test('without WebSockets the connection falls back to streaming and stays live', async ({
  browser,
}) => {
  const context = await browser.newContext();
  // A proxy that blocks WebSockets, as far as the page can tell.
  await context.addInitScript(() => {
    Object.defineProperty(window, 'WebSocket', { value: undefined, configurable: true });
  });
  const page = await context.newPage();
  await signInAs(page, 'tech', '/profile');
  const html = page.locator('html');
  await expect(html).toHaveAttribute('data-realtime-status', 'connected', { timeout: 15_000 });
  await expect(html).toHaveAttribute('data-realtime-transport', /^(http_stream|sse)$/);

  const other = await open(browser, 'tech', '/profile');
  const original = await page.getByTestId('profile-signature').inputValue();
  try {
    await other.page.getByTestId('profile-signature').fill(`Stream ${String(Date.now())}`);
    await other.page.getByTestId('profile-save').click();
    await expect(page.getByTestId('live-change-notice')).toBeVisible(LIVE);
  } finally {
    await other.page.getByTestId('profile-signature').fill(original);
    await other.page.getByTestId('profile-save').click();
    await expect(other.page.getByText('Your preferences were saved.').first()).toBeVisible();
    await other.context.close();
    await context.close();
  }
});

test('with every streaming transport blocked the page polls, says so, and still updates', async ({
  browser,
}) => {
  const context = await browser.newContext();
  await context.addInitScript(() => {
    Object.defineProperty(window, 'WebSocket', { value: undefined, configurable: true });
  });
  await context.route('**/connection/**', (route) => route.abort());
  const page = await context.newPage();
  await signInAs(page, 'admin', '/admin/roles');
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'polling', {
    timeout: 20_000,
  });
  await expect(page.getByTestId('realtime-polling-banner')).toBeVisible();

  // Another admin creates a role through the API; the polling refresh shows it.
  const other = await open(browser, 'admin', '/');
  const name = `E2E poll ${String(Date.now())}`;
  try {
    const created = await other.page.request.post('/api/v1/roles', {
      headers: { 'X-CSRF-Token': await csrf(other.page) },
      data: { name, permissions: [{ permission: 'reports.view', scope: 'all' }] },
    });
    expect(created.status()).toBe(201);
    await expect(page.getByTestId('roles-table').getByText(name)).toBeVisible({
      timeout: 20_000,
    });
  } finally {
    await deleteE2eRoles(other.page);
    await other.context.close();
    await context.close();
  }
});
