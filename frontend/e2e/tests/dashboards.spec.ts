import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-036 journeys (parity file 09, REQ-DSH-*): the home dashboard updates live within 2 seconds
 * in two browsers (REQ-DSH-016 AC1); a technician lands on "My work"; a user-made dashboard with a
 * quick chart is shared and appears in another person's picker; Arabic is right to left and
 * accessible. Suite-owned data only: the incidents go to the trash, the dashboard is deleted.
 */

const NAME = 'E2E team board';

interface Me {
  csrf_token: string;
  user: { id: string };
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const headers: Record<string, string> = { 'X-CSRF-Token': (await me(page)).csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function open(browser: Browser, user: 'admin' | 'tech', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  return { context, page };
}

/** The suite's own dashboards ("E2E …") left by an interrupted run. */
async function deleteE2eDashboards(page: Page): Promise<void> {
  const listed = (await (await call(page, 'GET', '/dashboards')).json()) as {
    items: { ref: string; name: string | null; version: number; can_edit: boolean }[];
  };
  for (const d of listed.items.filter((i) => i.name?.startsWith('E2E ') && i.can_edit)) {
    await call(page, 'DELETE', `/dashboards/${d.ref}`, undefined, d.version);
  }
}

test('the service desk dashboard updates live in two browsers within 2 seconds (REQ-DSH-016)', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const first = await open(browser, 'admin', '/dashboards/builtin%3Aservice_desk');
  const second = await open(browser, 'admin', '/dashboards/builtin%3Aservice_desk');
  const made: string[] = [];
  try {
    const kpi = (page: Page) => page.getByTestId('widget-open').getByTestId('widget-kpi-value');
    await expect(kpi(first.page)).toHaveText(/\d/);
    await expect(kpi(second.page)).toHaveText(/\d/);
    const before = Number((await kpi(first.page).innerText()).replace(/\D/g, ''));
    const self = await me(first.page);
    const created = await call(first.page, 'POST', '/incidents', {
      subject: 'E2E live dashboard',
      requester_id: self.user.id,
    });
    expect(created.status(), await created.text()).toBe(201);
    made.push(((await created.json()) as { id: string }).id);
    // Live: no reload; both browsers within 2 seconds (+ the 1 s refresh coalescing window).
    for (const page of [first.page, second.page]) {
      await expect(kpi(page)).toHaveText(String(before + 1), { timeout: 3_000 });
    }
    await expectAccessible(first.page, 'service desk dashboard');
  } finally {
    for (const id of made) {
      const found = await call(first.page, 'GET', `/incidents/${id}`);
      if (found.status() === 200) {
        const { version } = (await found.json()) as { version: number };
        await call(first.page, 'DELETE', `/incidents/${id}`, undefined, version);
      }
    }
    await first.context.close();
    await second.context.close();
  }
});

test('a technician lands on "My work"; a shared dashboard reaches their picker (REQ-DSH-002, 026)', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const admin = await open(browser, 'admin', '/dashboards');
  const tech = await open(browser, 'tech', '/');
  try {
    await deleteE2eDashboards(admin.page);
    await expect(tech.page.getByTestId('dashboard-title')).toHaveText('My work');

    await admin.page.getByTestId('dashboards-new').click();
    await admin.page.getByTestId('dashboards-new-name').fill(NAME);
    await admin.page.getByRole('dialog').getByRole('button', { name: 'Create' }).click();
    await expect(admin.page.getByTestId('dashboard-title')).toHaveText(NAME);
    // Edit mode opens for a new dashboard: add a quick chart and save.
    await admin.page.getByTestId('dashboard-add-widget').click();
    // The catalogue opens first (D-114); this journey builds a quick chart.
    await admin.page.getByTestId('dashboard-add-source').getByText('Quick chart').click();
    await admin.page.getByTestId('dashboard-add-title').fill('Open by priority');
    await expect(admin.page.getByTestId('dashboard-add-preview')).toBeVisible();
    await admin.page.getByTestId('dashboard-add-confirm').click();
    await admin.page.getByTestId('dashboard-done').click();
    await expect(admin.page.getByText('Open by priority')).toBeVisible();
    await admin.page.getByTestId('dashboard-share').click();
    await expect(admin.page.getByTestId('dashboard-share')).toHaveAttribute('aria-checked', 'true');
    await expectAccessible(admin.page, 'user-made dashboard');

    await tech.page.goto('/dashboards');
    const shared = tech.page.getByTestId('dashboards-group-shared');
    await expect(shared.getByText(NAME)).toBeVisible();
    await expectAccessible(tech.page, 'dashboard picker');
  } finally {
    await deleteE2eDashboards(admin.page);
    await admin.context.close();
    await tech.context.close();
  }
});

test('dashboards in Arabic: right to left, labels only, accessible (REQ-DSH-045, 046, 047)', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const { context, page } = await open(browser, 'admin', '/dashboards');
  try {
    const self = await me(page);
    const user = (await (await page.request.get(`/api/v1/users/${self.user.id}`)).json()) as {
      version: number;
    };
    const arabic = await call(
      page,
      'PATCH',
      `/users/${self.user.id}`,
      { ui_locale: 'ar' },
      user.version,
    );
    expect(arabic.status(), await arabic.text()).toBe(200);
    await page.goto('/dashboards/builtin%3Aservice_desk');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('dashboard-title')).toHaveText('مكتب الخدمة');
    await expect(page.getByTestId('widget-title-open')).toHaveText('الحوادث المفتوحة');
    const text = await page.locator('main').innerText();
    expect(text).not.toMatch(/dashboard_widget\.|dashboards\.|builtin:/);
    await expectAccessible(page, 'service desk dashboard (Arabic)');
  } finally {
    await resetLanguage(page);
    await context.close();
  }
});

test('the widget library: lists and trends on the service desk; the catalogue adds a widget (D-114)', async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const admin = await open(browser, 'admin', '/dashboards/builtin%3Aservice_desk');
  try {
    await deleteE2eDashboards(admin.page);
    const page = admin.page;
    // Ready-made: key numbers, created vs resolved, backlog, and lists of records.
    for (const id of ['overdue', 'due_today', 'created_vs_resolved', 'backlog_trend']) {
      await expect(page.getByTestId(`widget-title-${id}`)).toBeVisible();
    }
    await expect(page.getByTestId('widget-overdue_list')).toBeVisible();
    await expect(page.getByTestId('widget-type-created_vs_resolved')).toBeVisible(); // a chart
    await expectAccessible(page, 'service desk with the widget library');

    // A new dashboard of the suite's own, with one widget from the searchable catalogue.
    await page.goto('/dashboards');
    await page.getByTestId('dashboards-new').click();
    await page.getByTestId('dashboards-new-name').fill(`${NAME} library`);
    await page.getByRole('dialog').getByRole('button', { name: 'Create' }).click();
    await expect(page.getByTestId('dashboard-title')).toHaveText(`${NAME} library`);
    await page.getByTestId('dashboard-add-widget').click();
    await page.getByTestId('dashboard-catalogue-search').fill('recently');
    await page.getByRole('radio', { name: /Recently updated/ }).check();
    await expect(page.getByTestId('dashboard-add-preview')).toBeVisible();
    await expect(page.getByRole('radio', { name: /SLA breached/ })).toHaveCount(0); // filtered out
    await page.getByTestId('dashboard-catalogue-search').fill('');
    await expect(page.getByRole('radio', { name: /SLA breached/ })).toBeDisabled();
    await expectAccessible(page, 'widget catalogue');
    await page.getByTestId('dashboard-catalogue-search').fill('recently');
    await page.getByRole('radio', { name: /Recently updated/ }).check();
    await page.getByTestId('dashboard-add-confirm').click();
    await page.getByTestId('dashboard-done').click();
    await expect(page.getByText('Recently updated').last()).toBeVisible();
  } finally {
    await deleteE2eDashboards(admin.page);
    await admin.context.close();
  }
});
