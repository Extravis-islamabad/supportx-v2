import { expect, test, type Browser, type Page } from '@playwright/test';

import { signInAs } from './helpers';

/**
 * QA WP-036 BUG-01: two people edit the same dashboard. The first saves; the second, still
 * editing, keeps their draft and meets the conflict dialog on Done, which says who saved first.
 * Never a silent overwrite, never a silently lost edit. Two separate signed-in sessions (the
 * suite's admin holds the edit right; the seeded admin needs two-step sign-in).
 */

interface Board {
  ref: string;
  version: number;
  body: { widgets: { id: string; place: { x: number; y: number; w: number; h: number } }[] };
}

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function session(browser: Browser) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, 'admin', '/dashboards');
  return { context, page };
}

test('BUG-01: a second editor keeps their draft and meets the conflict dialog', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const first = await session(browser);
  const second = await session(browser);
  const widgets = ['a', 'b'].map((id, i) => ({
    id,
    title: `E2E ${id}`,
    report: { entity: 'incident', measures: ['open_count'], chart: 'kpi' },
    place: { x: i * 3, y: 0, w: 3, h: 2 },
  }));
  const made = (await (
    await call(first.page, 'POST', '/dashboards', { name: 'E2E conflict', body: { widgets } })
  ).json()) as Board;
  try {
    for (const { page } of [first, second]) {
      await page.goto(`/dashboards/${made.ref}`);
      await page.getByTestId('dashboard-edit').click();
    }
    await first.page.getByTestId('widget-move_right-a').click();
    await second.page.getByTestId('widget-wider-b').click();
    await first.page.getByTestId('dashboard-done').click();
    await expect(first.page.getByTestId('dashboard-edit')).toBeVisible();

    // The first save reaches the second session live; its edit and draft stay.
    await second.page.waitForTimeout(1500);
    await expect(second.page.getByTestId('dashboard-done')).toBeVisible();
    await second.page.getByTestId('dashboard-done').click();
    const dialog = second.page.getByRole('dialog');
    await expect(dialog.getByText('Someone else changed this')).toBeVisible();
    await expect(dialog).toContainText('Adel E2E Admin');

    // "Keep my changes" saves the second draft on top of the first save, nothing lost silently.
    await dialog.getByRole('button', { name: 'Keep my changes' }).click();
    await expect(second.page.getByTestId('dashboard-edit')).toBeVisible();
    const saved = (await (
      await call(first.page, 'GET', `/dashboards/${made.ref}`)
    ).json()) as Board;
    expect(saved.version).toBe(made.version + 2);
    expect(saved.body.widgets.find((w) => w.id === 'b')?.place.w).toBe(4);
  } finally {
    const latest = (await (
      await call(first.page, 'GET', `/dashboards/${made.ref}`)
    ).json()) as Board;
    await call(first.page, 'DELETE', `/dashboards/${made.ref}`, undefined, latest.version);
    await first.context.close();
    await second.context.close();
  }
});
