import { expect, test, type Browser, type Page } from '@playwright/test';

import { PORTAL_URL } from '../stack';
import { expectAccessible, signInAs } from './helpers';

/**
 * WP-032: the portal home and its one search box, end to end.
 *
 * 1. The home's summary moves within a second when a technician resolves the requester's
 *    incident (REQ-PRT-002 AC1), with no reload.
 * 2. The search finds the requester's own request in its group; with nothing found, "report an
 *    issue" opens the form with the words as its subject (REQ-PRT-003 AC1, AC3).
 * 3. An admin's change to the search sources reaches an open portal at once (REQ-PRT-031 AC2).
 *
 * Suite-owned data only: incidents are named "E2E …" and go to the trash at the end; the portal
 * settings are put back as they were.
 */

const LIVE = { timeout: 3_000 };

interface Made {
  id: string;
  display_id: string;
  version: number;
}

async function open(browser: Browser, user: 'admin' | 'limited', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

/** The API as the page's signed-in user (same session cookie, CSRF header, If-Match). */
async function call(
  page: Page,
  method: string,
  path: string,
  { body, version }: { body?: unknown; version?: number } = {},
) {
  const base = new URL(page.url()).origin;
  const me = (await (await page.request.get(`${base}/api/v1/auth/me`)).json()) as {
    csrf_token: string;
  };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`${base}/api/v1${path}`, { method, data: body, headers });
}

async function report(page: Page, subject: string): Promise<string> {
  await page.goto(`${PORTAL_URL}/requests/new`);
  await page.getByTestId('portal-report-subject').fill(subject);
  await page.getByTestId('portal-report-send').click();
  await expect(page).toHaveURL(/\/requests\/[0-9a-f-]{36}$/);
  return page.url().split('/').at(-1) ?? '';
}

async function trash(admin: Page, ids: string[]): Promise<void> {
  for (const id of ids) {
    const found = await call(admin, 'GET', `/incidents/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as Made;
    await call(admin, 'DELETE', `/incidents/${id}`, { version });
  }
}

test('the home summary follows a resolve live, and the search box finds or reports', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const subject = `E2E Portal home ${String(Date.now())}`;
  const requester = await open(browser, 'limited', `${PORTAL_URL}/`);
  const admin = await open(browser, 'admin', '/');
  const made: string[] = [];
  const page = requester.page;
  try {
    const id = await report(page, subject);
    made.push(id);
    await page.goto(`${PORTAL_URL}/`);
    for (const start of ['report', 'request', 'answer']) {
      await expect(page.getByTestId(`portal-start-${start}`)).toBeVisible();
    }
    const summary = page.getByTestId('portal-summary-open');
    await expect(summary).toBeVisible(LIVE);
    const before = (await summary.textContent()) ?? '';
    await expectAccessible(page, 'portal home');

    const current = (await (await call(admin.page, 'GET', `/incidents/${id}`)).json()) as Made;
    const resolved = await call(admin.page, 'POST', `/incidents/${id}/actions/resolve`, {
      version: current.version,
      body: { resolution: '<p>E2E: reset done.</p>' },
    });
    expect(resolved.status(), await resolved.text()).toBe(200);
    await expect(summary).not.toHaveText(before, LIVE); // "Resolved" now counts it

    // Search: their own request in its group; nonsense offers a report with the words.
    await page.getByTestId('portal-home-search').locator('input').fill(subject);
    await page.getByTestId('portal-home-search').locator('input').press('Enter');
    await expect(page.getByTestId('portal-search-requests')).toContainText(subject, LIVE);
    await expectAccessible(page, 'portal search');
    const words = `zz-e2e-nothing-${String(Date.now())}`;
    await page.getByTestId('portal-search-input').locator('input').fill(words);
    await expect(page.getByTestId('portal-search-nothing')).toBeVisible(LIVE);
    await page.getByTestId('portal-search-report').click();
    await expect(page.getByTestId('portal-report-subject')).toHaveValue(words);
  } finally {
    await trash(admin.page, made);
    await Promise.all([requester.context.close(), admin.context.close()]);
  }
});

test('a change to the search sources reaches an open portal at once', async ({ browser }) => {
  const requester = await open(browser, 'limited', `${PORTAL_URL}/search?q=e2e`);
  const admin = await open(browser, 'admin', '/');
  const settings = (await (await call(admin.page, 'GET', '/portal/settings')).json()) as {
    search_sources: string[];
    version: number;
  };
  try {
    await expect(requester.page.getByTestId('portal-search')).toBeVisible(LIVE);
    const changed = await call(admin.page, 'PATCH', '/portal/settings', {
      body: { search_sources: ['requests'] },
      version: settings.version,
    });
    expect(changed.status(), await changed.text()).toBe(200);
    // Only "your requests" is searched now: the catalog group never shows, with no reload.
    await requester.page.getByTestId('portal-search-input').locator('input').fill('vpn');
    await expect(requester.page.getByTestId('portal-search-items')).toHaveCount(0, LIVE);
  } finally {
    const now = (await (await call(admin.page, 'GET', '/portal/settings')).json()) as {
      version: number;
    };
    await call(admin.page, 'PATCH', '/portal/settings', {
      body: { search_sources: settings.search_sources },
      version: now.version,
    });
    await Promise.all([requester.context.close(), admin.context.close()]);
  }
});
