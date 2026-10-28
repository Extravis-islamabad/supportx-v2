import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-035 journeys (parity file 09): the reports home and a built-in report in English and
 * Arabic (RTL, labels only, axe); a scheduled report that appears, pauses and is deleted live
 * (REQ-RPT-052, 056). Suite-owned data only: the schedule is deleted at the end.
 */

const BUILTIN = '/reports/builtin/incidents_open_by_priority';
const TITLE_EN = 'Open incidents by priority';
const TITLE_AR = 'الحوادث المفتوحة حسب الأولوية';
const SCHEDULE_TITLE = 'E2E weekly open incidents';

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function open(browser: Browser, path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, 'admin', path);
  return { context, page };
}

interface Schedule {
  id: string;
  title: string;
  version: number;
}

/** Delete the suite's own schedules ("E2E …") left by an earlier, interrupted run. */
async function deleteE2eSchedules(page: Page): Promise<void> {
  const listed = (await (await call(page, 'GET', '/reports/schedules')).json()) as {
    items: Schedule[];
  };
  for (const item of listed.items.filter((s) => s.title.startsWith('E2E '))) {
    const gone = await call(
      page,
      'DELETE',
      `/reports/schedules/${item.id}`,
      undefined,
      item.version,
    );
    expect(gone.status(), await gone.text()).toBe(204);
  }
}

/** No internal code reaches the screen (CLAUDE.md rule d). */
async function expectNoRawCodes(page: Page): Promise<void> {
  const text = await page.locator('main').innerText();
  expect(text).not.toMatch(
    /incidents_open_by_priority|status_category|builtin:|report_export_|\bp[1-4]\b/,
  );
}

test('reports home and a built-in report (English)', async ({ browser }) => {
  test.setTimeout(120_000);
  const { context, page } = await open(browser, '/reports');
  try {
    await expect(page.getByTestId('reports-search')).toBeVisible();
    await expect(page.getByTestId(`reports-open-builtin:incidents_open_by_priority`)).toBeVisible();
    await expectAccessible(page, 'reports home');

    await page.goto(BUILTIN);
    await expect(page.getByTestId('report-title')).toHaveText(TITLE_EN);
    await expect(page.getByTestId('report-result')).toBeVisible();
    await expect(page.getByTestId('report-filter-words')).toBeVisible();
    await expectNoRawCodes(page);
    await expectAccessible(page, 'built-in report');

    // The export dialog (the file itself: the export journey, after the worker fix).
    await page.getByTestId('report-export').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expectAccessible(page, 'export dialog');
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
  } finally {
    await context.close();
  }
});

test('a scheduled report appears, pauses and is deleted live', async ({ browser }) => {
  test.setTimeout(120_000);
  const { context, page } = await open(browser, '/reports');
  try {
    await deleteE2eSchedules(page);
    const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
      user: { id: string };
    };
    await page.getByTestId('report-schedules').click();
    await expect(page.getByRole('dialog')).toBeVisible();

    // Made elsewhere (the API, as another tab would): it appears in the open drawer.
    const made = await call(page, 'POST', '/reports/schedules', {
      title: SCHEDULE_TITLE,
      report_ref: 'builtin:incidents_open_by_priority',
      frequency: 'weekly',
      at_time: '07:00',
      time_zone: 'Asia/Riyadh',
      start_date: new Date().toISOString().slice(0, 10),
      weekdays: [0],
      recipient_users: [me.user.id],
      recipient_groups: [],
      format: 'csv',
    });
    expect(made.status(), await made.text()).toBe(201);
    const schedule = (await made.json()) as Schedule;
    await expect(page.getByTestId(`schedule-status-${schedule.id}`)).toHaveText('Active');
    await expectAccessible(page, 'scheduled reports');

    await page.getByTestId(`schedule-pause-${schedule.id}`).click();
    await expect(page.getByTestId(`schedule-status-${schedule.id}`)).toHaveText('Paused');
    await expect(page.getByTestId(`schedule-resume-${schedule.id}`)).toBeVisible();

    await page.getByTestId(`schedule-delete-${schedule.id}`).click();
    await page.locator('.ant-popconfirm:visible').getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByTestId(`schedule-status-${schedule.id}`)).toHaveCount(0);
  } finally {
    await deleteE2eSchedules(page);
    await context.close();
  }
});

test('reports in Arabic: right to left, labels only, accessible', async ({ browser }) => {
  test.setTimeout(120_000);
  const { context, page } = await open(browser, '/reports');
  try {
    const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
      user: { id: string };
    };
    const user = (await (await page.request.get(`/api/v1/users/${me.user.id}`)).json()) as {
      version: number;
    };
    const arabic = await call(
      page,
      'PATCH',
      `/users/${me.user.id}`,
      { ui_locale: 'ar' },
      user.version,
    );
    expect(arabic.status(), await arabic.text()).toBe(200);

    await page.goto('/reports');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('reports-search')).toBeVisible();
    await expectAccessible(page, 'reports home (Arabic)');

    await page.goto(BUILTIN);
    await expect(page.getByTestId('report-title')).toHaveText(TITLE_AR);
    await expect(page.getByTestId('report-result')).toBeVisible();
    await expectNoRawCodes(page);
    await expectAccessible(page, 'built-in report (Arabic)');
    await page.screenshot({ path: 'test-results/report-ar.png', fullPage: true });

    await page.getByTestId('report-export').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expectAccessible(page, 'export dialog (Arabic)');
  } finally {
    await resetLanguage(page);
    await context.close();
  }
});
