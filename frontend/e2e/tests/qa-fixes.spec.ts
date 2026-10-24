import { expect, test, type Page } from '@playwright/test';

import { resetLanguage, signInAs } from './helpers';

/**
 * WP-020-FIX: the findings of the WP-020 QA report that only a real browser can show (layout,
 * fonts, overlaps, scrolling, reloads, presence). Test names start with the report's IDs.
 *
 * Suite-owned data only ("E2E …" incidents, trashed at the end and removed by the teardown); the
 * suite admin's layout and language are put back at the end.
 */

const stamp = () => String(Date.now()).slice(-7);

interface Me {
  csrf_token: string;
  user: { id: string };
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

async function call(
  page: Page,
  method: string,
  path: string,
  { body, version }: { body?: unknown; version?: number } = {},
) {
  const headers: Record<string, string> = { 'X-CSRF-Token': (await me(page)).csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

/** Change a preference of the signed-in user through the API (layout, language). */
async function prefer(page: Page, body: Record<string, unknown>): Promise<void> {
  const id = (await me(page)).user.id;
  const user = (await (await call(page, 'GET', `/users/${id}`)).json()) as { version: number };
  const saved = await call(page, 'PATCH', `/users/${id}`, { body, version: user.version });
  expect(saved.status(), await saved.text()).toBe(200);
}

interface Incident {
  id: string;
  display_id: string;
  version: number;
}

const created: string[] = [];

async function incident(page: Page, subject: string): Promise<Incident> {
  const response = await call(page, 'POST', '/incidents', {
    body: { subject, requester_id: (await me(page)).user.id },
  });
  expect(response.status(), await response.text()).toBe(201);
  const item = (await response.json()) as Incident;
  created.push(item.id);
  return item;
}

test.afterAll(async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, 'admin');
  for (const id of created) {
    const found = await call(page, 'GET', `/incidents/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as Incident;
    await call(page, 'DELETE', `/incidents/${id}`, { version });
  }
  await prefer(page, { nav_layout: 'top' });
  await resetLanguage(page);
  await context.close();
});

/**
 * No sideways page scroll: the document is never wider than the window, once the layout has
 * settled (the side bar collapses to icons on narrow screens with a short animation).
 */
async function expectNoSidewaysScroll(page: Page, label: string): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(
          // Overflow past the visible width (a reserved scrollbar gutter is not overflow).
          () =>
            Math.max(
              0,
              document.documentElement.scrollWidth - document.documentElement.clientWidth,
            ),
        ),
      {
        message: `${label}: page wider than the window`,
        timeout: 3_000,
      },
    )
    .toBe(0);
}

test('BUG-07: no sideways scroll from 360 px up, in every layout, on list, record and form', async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInAs(page, 'admin', '/incidents');
  const item = await incident(page, `E2E Narrow ${stamp()} printer on the third floor`);
  const pages = [
    ['list', '/incidents', 'inc-table'],
    ['record', `/incidents/${item.id}`, 'inc-heading'],
    ['form', '/incidents/new', 'inc-subject'],
  ] as const;
  for (const layout of ['top', 'side', 'side_compact'] as const) {
    await prefer(page, { nav_layout: layout });
    for (const width of [360, 390, 768, 1024, 1440]) {
      await page.setViewportSize({ width, height: 800 });
      for (const [name, path, ready] of pages) {
        await page.goto(path);
        await expect(page.getByTestId(ready)).toBeVisible();
        await expectNoSidewaysScroll(page, `${layout} ${String(width)}px ${name}`);
      }
      // The header's controls stay reachable (collapsed into icons and the user menu).
      await expect(page.getByTestId('user-menu')).toBeInViewport();
      await expect(page.getByTestId('appearance-menu')).toBeInViewport();
    }
  }
  await page.setViewportSize({ width: 390, height: 800 });
  await page.screenshot({ path: 'test-results/qa-bug-07-390.png', fullPage: true });
});

test('BUG-04: the language picked survives a reload and follows the user to another session', async ({
  browser,
}) => {
  const first = await browser.newContext();
  const page = await first.newPage();
  await signInAs(page, 'admin', '/incidents');
  try {
    await page.getByTestId('appearance-menu').click();
    await page.getByTestId('language-select').click();
    await page.locator('.ant-select-item-option[title="العربية"]').click();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await page.keyboard.press('Escape');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('inc-table')).toBeVisible();
    const second = await browser.newContext();
    const other = await second.newPage();
    // Sign in without the helper's language reset: the stored choice must arrive as it is.
    await other.goto('/incidents');
    await other.locator('#username').fill('e2e.admin@demo.test');
    await other.locator('#kc-login').click();
    const { passwordOf } = await import('../stack');
    await other.locator('#password').fill(passwordOf('admin'));
    await other.locator('#kc-login').click();
    await expect(other.locator('html')).toHaveAttribute('lang', 'ar');
    await second.close();
  } finally {
    await resetLanguage(page);
    await first.close();
  }
});

test('BUG-16: long subjects are cut and Restore stays in view in the trash', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await signInAs(page, 'admin', '/incidents');
  const item = await incident(page, `E2E Long ${stamp()} ${'very long subject '.repeat(12)}`);
  const removed = await call(page, 'DELETE', `/incidents/${item.id}`, { version: item.version });
  expect(removed.status()).toBe(204);
  await page.goto('/incidents');
  await page.getByTestId('inc-mode').getByText('Trash', { exact: true }).click();
  const restore = page.getByTestId(`inc-restore-${item.display_id}`);
  await expect(restore).toBeVisible();
  await expect(restore).toBeInViewport({ ratio: 1 });
  const restored = await call(page, 'GET', `/incidents/${item.id}`);
  expect(restored.status()).toBe(404); // still in the trash: the test did not restore it
});

test('C1, C2, C5: counter clear of the buttons; Arabic in a Naskh face; nothing shifts or covers the title', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signInAs(page, 'admin', '/incidents');
  const item = await incident(page, `E2E Layout ${stamp()}`);
  await page.goto(`/incidents/${item.id}`);
  await expect(page.getByTestId('inc-heading')).toBeVisible();

  // C5: opening a dialog does not move the header.
  const before = await page.getByTestId('appearance-menu').boundingBox();
  await page.getByTestId('inc-action-cancel').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const during = await page.getByTestId('appearance-menu').boundingBox();
  expect(during?.x).toBe(before?.x);

  // C1: the "0 / 500" counter sits above the buttons, not under them.
  const count = await dialog.locator('.ant-input-data-count').boundingBox();
  const buttons = await dialog.locator('.ant-modal-footer').boundingBox();
  expect((count?.y ?? 0) + (count?.height ?? 0)).toBeLessThanOrEqual(buttons?.y ?? 0);
  await dialog.getByRole('button', { name: 'Keep incident' }).click();
  await expect(dialog).toBeHidden();

  // C5: the Appearance panel leaves the page title visible.
  await page.getByTestId('appearance-menu').click();
  const panel = await page.getByTestId('appearance-controls').boundingBox();
  const title = await page.getByTestId('inc-heading').locator('bdi').boundingBox();
  const overlaps =
    panel !== null &&
    title !== null &&
    panel.x < title.x + title.width &&
    title.x < panel.x + panel.width &&
    panel.y < title.y + title.height &&
    title.y < panel.y + panel.height;
  expect(overlaps).toBe(false);

  // C2: Arabic text is drawn in a Naskh face (Nastaliq clipped button labels).
  try {
    await page.getByTestId('language-select').click();
    await page.locator('.ant-select-item-option[title="العربية"]').click();
    await page.keyboard.press('Escape');
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
    await page.goto('/incidents/new');
    await expect(page.getByTestId('inc-save')).toBeVisible();
    const cdp = await page.context().newCDPSession(page);
    const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
    const { nodeId } = await cdp.send('DOM.querySelector', {
      nodeId: root.nodeId,
      selector: '[data-testid="inc-save"] span',
    });
    await cdp.send('CSS.enable');
    const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
    expect(fonts.map((f) => f.familyName).join(', ')).not.toMatch(/Nastaliq|Nastaleeq/);
    // C2: the site's help line never runs into the label under it.
    const help = await page
      .locator('#field-site_id_help, .ant-form-item-explain')
      .first()
      .boundingBox();
    const technician = await page.getByText('الفني', { exact: true }).first().boundingBox();
    if (help !== null && technician !== null && technician.y > help.y) {
      expect(help.y + help.height).toBeLessThanOrEqual(technician.y + 1);
    }
  } finally {
    await resetLanguage(page);
  }
});

test('C3: in the side bar layout the sidebar border runs the full height of a long page', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 700 });
  await signInAs(page, 'admin', '/incidents');
  await prefer(page, { nav_layout: 'side' });
  try {
    const item = await incident(page, `E2E Tall ${stamp()}`);
    await page.goto(`/incidents/${item.id}`);
    await expect(page.getByTestId('inc-heading')).toBeVisible();
    await page.evaluate(() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    const sider = await page.locator('.ant-layout-sider').boundingBox();
    const doc = await page.evaluate(() => document.documentElement.scrollHeight);
    const scrolled = await page.evaluate(() => window.scrollY);
    // The sider reaches the bottom of the page (its border with it).
    expect((sider?.y ?? 0) + scrolled + (sider?.height ?? 0)).toBeGreaterThanOrEqual(doc - 1);
  } finally {
    await prefer(page, { nav_layout: 'top' });
  }
});

test('BUG-13: reloading a record leaves no "you, in another window" ghost', async ({ page }) => {
  await signInAs(page, 'admin', '/incidents');
  const item = await incident(page, `E2E Presence ${stamp()}`);
  await page.goto(`/incidents/${item.id}`);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected');
  await expect(page.getByTestId('inc-heading')).toBeVisible();
  // Only this window views the record: no presence, within a few seconds of the reload.
  await expect(page.getByTestId('presence')).toHaveCount(0, { timeout: 5_000 });
  await page.waitForTimeout(3_000);
  await expect(page.getByTestId('presence')).toHaveCount(0);
});
