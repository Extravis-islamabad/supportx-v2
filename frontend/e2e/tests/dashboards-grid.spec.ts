import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * The free-form dashboard grid (D-110, react-grid-layout): loaded only in edit mode; keyboard
 * buttons kept beside dragging; in Arabic the first column is on the right and dragging follows
 * what the eye sees. Suite-owned data only: the dashboard is deleted at the end.
 */

const NAME = 'E2E grid board';

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

const widget = (id: string, x: number) => ({
  id,
  title: id === 'a' ? 'Alpha tile' : 'Beta tile',
  report: { entity: 'incident', measures: ['open_count'], chart: 'kpi' },
  place: { x, y: 0, w: 3, h: 2 },
});

interface Dashboard {
  ref: string;
  version: number;
  body: { widgets: { id: string; place: { x: number } }[] };
}

async function board(page: Page): Promise<Dashboard> {
  const listed = (await (await call(page, 'GET', '/dashboards')).json()) as {
    items: { ref: string; name: string | null; version: number }[];
  };
  for (const old of listed.items.filter((d) => d.name === NAME)) {
    await call(page, 'DELETE', `/dashboards/${old.ref}`, undefined, old.version);
  }
  const made = await call(page, 'POST', '/dashboards', {
    name: NAME,
    shared: false,
    body: { widgets: [widget('a', 0), widget('b', 6)] },
  });
  expect(made.status(), await made.text()).toBe(201);
  return (await made.json()) as Dashboard;
}

async function saved(page: Page, ref: string): Promise<Record<string, number>> {
  const found = (await (await call(page, 'GET', `/dashboards/${ref}`)).json()) as Dashboard;
  return Object.fromEntries(found.body.widgets.map((w) => [w.id, w.place.x]));
}

/** Drag a widget by its title, `columns` grid columns to the visual right (negative: left). */
async function drag(page: Page, id: string, columns: number): Promise<void> {
  const grid = page.getByTestId('dashboard-free-grid');
  const width = (await grid.boundingBox())?.width ?? 1200;
  const handle = page.getByTestId(`widget-title-${id}`);
  const box = await handle.boundingBox();
  if (!box) throw new Error('no title to grab');
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + (columns * width) / 12 / 2, y, { steps: 5 });
  await page.mouse.move(x + (columns * width) / 12, y, { steps: 5 });
  await page.mouse.up();
}

for (const language of ['en', 'ar'] as const) {
  test(`free-form grid in ${language === 'en' ? 'English' : 'Arabic'}: lazy, keyboard kept, drags as seen`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: 1440, height: 900 });
    await signInAs(page, 'admin', '/dashboards');
    const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
      user: { id: string };
    };
    let dashboard: Dashboard | undefined;
    try {
      if (language === 'ar') {
        const user = (await (await page.request.get(`/api/v1/users/${me.user.id}`)).json()) as {
          version: number;
        };
        await call(page, 'PATCH', `/users/${me.user.id}`, { ui_locale: 'ar' }, user.version);
      }
      dashboard = await board(page);
      const loaded: string[] = [];
      page.on('request', (request) => {
        if (/FreeGrid|react-grid-layout/.test(request.url())) loaded.push(request.url());
      });
      await page.goto(`/dashboards/${dashboard.ref}`);
      await expect(page.getByTestId('widget-title-a')).toBeVisible();
      expect(loaded).toEqual([]); // viewers never download the grid library

      // Read-only grid: x = 0 is the first column, on the left in English, the right in Arabic.
      const a = await page.getByTestId('widget-a').boundingBox();
      const b = await page.getByTestId('widget-b').boundingBox();
      expect(a && b && (language === 'ar' ? a.x > b.x : a.x < b.x)).toBe(true);

      await page.getByTestId('dashboard-edit').click();
      await expect(page.getByTestId('dashboard-free-grid')).toBeVisible();
      expect(loaded.length).toBeGreaterThan(0); // loaded now, in edit mode
      // The free-form grid keeps the same sides as the read-only one.
      const ea = await page.getByTestId('free-a').boundingBox();
      const eb = await page.getByTestId('free-b').boundingBox();
      expect(ea && eb && (language === 'ar' ? ea.x > eb.x : ea.x < eb.x)).toBe(true);
      // Keyboard buttons stay beside dragging (accessibility, D-110).
      await expect(page.getByTestId('widget-move_right-a')).toBeVisible();
      await expectAccessible(page, `dashboard edit mode (${language})`);

      // Drag "a" two columns towards the end of the line: to the right in English, to the left
      // in Arabic. Either way its column (x) grows from 0.
      await drag(page, 'a', language === 'ar' ? -2 : 2);
      await page.getByTestId('dashboard-done').click();
      await expect(page.getByTestId('dashboard-free-grid')).toBeHidden();
      const ref = dashboard.ref;
      await expect.poll(async () => (await saved(page, ref)).a).toBeGreaterThan(0);
    } finally {
      if (dashboard) {
        const found = (await (
          await call(page, 'GET', `/dashboards/${dashboard.ref}`)
        ).json()) as Dashboard;
        await call(page, 'DELETE', `/dashboards/${dashboard.ref}`, undefined, found.version);
      }
      await resetLanguage(page);
    }
  });
}
