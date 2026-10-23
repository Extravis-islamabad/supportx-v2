import { expect, test, type Browser, type Page } from '@playwright/test';

import { PORTAL_URL, SEEDED, USERS } from '../stack';
import { deleteE2eRoles, expectAccessible, signIn, signInAs } from './helpers';

/**
 * WP-012 walking skeleton, end to end in real browsers: announcements live in two browsers, a
 * scheduled one going live at its start with no reload, who sees what (requester, site-scoped
 * technician, another tenant), the 409 that says who changed what, labels and accessibility.
 *
 * Suite-owned data only: every announcement, site and role is named "E2E …". Announcements are
 * moved to the trash at the end of each test and hard-deleted by global-teardown, with their
 * history (tooling/e2e_fixtures.py). Seeded users are only signed in, never changed.
 */

const LIVE = { timeout: 8_000 };
const stamp = () => String(Date.now()).slice(-7);

interface Item {
  id: string;
  display_id: string;
  title: string;
  version: number;
}

async function open(browser: Browser, user: 'tech' | 'admin' | 'limited', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

async function openSeeded(browser: Browser, who: keyof typeof SEEDED, url: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signIn(page, SEEDED[who].email, SEEDED[who].password, url);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

async function csrf(page: Page): Promise<string> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  return me.csrf_token;
}

/** The API as the page's signed-in user (same session cookie, CSRF header, If-Match). */
async function call(
  page: Page,
  method: string,
  path: string,
  { body, version }: { body?: unknown; version?: number } = {},
) {
  const headers: Record<string, string> = { 'X-CSRF-Token': await csrf(page) };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function create(page: Page, values: Record<string, unknown>): Promise<Item> {
  const response = await call(page, 'POST', '/announcements', {
    body: { body: 'Written by the e2e suite.', show_as_banner: true, ...values },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as Item;
}

async function act(page: Page, item: Item, action: string): Promise<Item> {
  const response = await call(page, 'POST', `/announcements/${item.id}/${action}`, {
    version: item.version,
  });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as Item;
}

/** Move the suite's announcements to the trash (global-teardown removes them for good). */
async function trash(page: Page, ids: string[]): Promise<void> {
  for (const id of ids) {
    const found = await call(page, 'GET', `/announcements/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as Item;
    await call(page, 'DELETE', `/announcements/${id}`, { version });
  }
}

test.beforeAll(async ({ browser }) => {
  // The journeys publish as the author: they need the dev tenant's four-eyes rule off (its
  // default). It is never changed here; the backend tests cover it on and off.
  const admin = await open(browser, 'admin', '/');
  const settings = (await (await call(admin.page, 'GET', '/announcements/settings')).json()) as {
    require_second_publisher: boolean;
  };
  await admin.context.close();
  expect(settings.require_second_publisher, 'Demo Company has the four-eyes rule on').toBe(false);
});

test('staff: a new announcement and its edits appear live in another browser; a stale save says who changed what; reasons reach the history', async ({
  browser,
}) => {
  test.setTimeout(150_000);
  const admin = await open(browser, 'admin', '/announcements');
  const tech = await open(browser, 'tech', '/announcements');
  const title = `E2E Live ${stamp()}`;
  let id = '';
  try {
    // Created through the UI; the technician's list shows it without a reload.
    await admin.page.getByTestId('ann-new').click();
    await admin.page.getByTestId('ann-title').fill(title);
    await admin.page.getByTestId('ann-body').fill('Line one\nLine two');
    await admin.page.getByTestId('ann-save').click();
    await expect(admin.page.getByTestId('ann-heading')).toHaveText(title);
    id = admin.page.url().split('/').at(-1) ?? '';
    await expect(tech.page.getByText(title)).toBeVisible(LIVE);

    // The technician opens it; the admin's edit shows on that open page by itself.
    await tech.page.getByText(title).click();
    await expect(tech.page.getByTestId('ann-heading')).toHaveText(title);
    await admin.page.getByTestId('ann-edit').click();
    await admin.page.getByTestId('ann-title').fill(`${title} (updated)`);
    await admin.page.getByTestId('ann-save').click();
    await expect(tech.page.getByTestId('ann-heading')).toHaveText(`${title} (updated)`, LIVE);

    // Two windows editing: the second save gets the 409 with who changed which field.
    const second = await open(browser, 'admin', `/announcements/${id}`);
    await second.page.getByTestId('ann-edit').click();
    await admin.page.getByTestId('ann-edit').click();
    await admin.page.getByTestId('ann-body').fill('Changed in the first window');
    await admin.page.getByTestId('ann-save').click();
    await expect(second.page.getByTestId('live-change-notice')).toBeVisible(LIVE);
    await second.page.getByTestId('ann-title').fill(`${title} (second)`);
    await second.page.getByTestId('ann-save').click();
    const who = second.page.getByTestId('conflict-who');
    await expect(who).toContainText('Adel E2E Admin saved it at');
    await expect(who).toContainText('Changed: Message.');
    await second.page.screenshot({ path: 'test-results/announcement-conflict.png' });
    await second.page.getByRole('button', { name: 'Reload their version' }).click();
    await second.context.close();

    // Status actions in their fixed order, with a reason that lands on the History tab.
    await admin.page.getByTestId('ann-action-publish').click();
    await expect(admin.page.getByTestId('ann-status')).toHaveText('Published');
    await expect(tech.page.getByTestId('ann-status')).toHaveText('Published', LIVE);
    await admin.page.getByTestId('ann-action-unpublish').click();
    await admin.page.getByTestId('ann-reason').fill('Wrong date in the text');
    await admin.page.getByRole('dialog').getByRole('button', { name: 'Unpublish' }).click();
    await expect(admin.page.getByTestId('ann-status')).toHaveText('Draft');
    await admin.page.getByRole('tab', { name: /History/ }).click();
    await expect(admin.page.getByText('Reason: Wrong date in the text')).toBeVisible();
    await expect(admin.page.getByTestId('ann-history')).toContainText('Status: Published → Draft');
    // The technician (not the owner, no publish permission) sees why each action is disabled.
    await expect(tech.page.getByTestId('ann-action-publish-reason')).toHaveAttribute(
      'data-reason',
      'no_permission',
    );
  } finally {
    await trash(admin.page, [id].filter(Boolean));
    await admin.context.close();
    await tech.context.close();
  }
});

test('scheduled: published to start one minute ahead, it appears on other screens at that moment without a reload', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const admin = await open(browser, 'admin', '/announcements');
  const tech = await open(browser, 'tech', '/');
  const requester = await openSeeded(browser, 'arabic', `${PORTAL_URL}/`);
  const title = `E2E Scheduled ${stamp()}`;
  let item: Item | undefined;
  try {
    const start = Date.now() + 60_000;
    item = await create(admin.page, {
      title,
      severity: 'critical',
      publish_from: new Date(start).toISOString(),
    });
    item = await act(admin.page, item, 'publish');
    const banner = tech.page.getByTestId(`announcement-banner-${item.id}`);
    const card = requester.page.getByTestId(`portal-announcement-${item.id}`);
    // Published, but not yet: nobody sees it.
    await tech.page.waitForTimeout(5_000);
    await expect(banner).toHaveCount(0);
    await expect(card).toHaveCount(0);
    // At the start it shows up by itself on both (no reload, no navigation).
    await expect(banner).toBeVisible({ timeout: 90_000 });
    await expect(card).toBeVisible({ timeout: 30_000 });
    expect(Date.now()).toBeGreaterThanOrEqual(start);
    await expect(banner).toContainText(`Critical: ${title}`);
    await expect(card).toContainText(`حرج: ${title}`); // the requester's portal is in Arabic
    await tech.page.screenshot({ path: 'test-results/announcement-banner.png' });
  } finally {
    await trash(admin.page, item === undefined ? [] : [item.id]);
    await Promise.all([admin.context.close(), tech.context.close(), requester.context.close()]);
  }
});

test('requester: never sees drafts, archived, scheduled or other sites’ announcements, in lists, banners, realtime or by ID', async ({
  browser,
}) => {
  const admin = await open(browser, 'admin', '/announcements');
  const s = stamp();
  const site = await call(admin.page, 'POST', '/organization/sites', {
    body: { name: `E2E Site ${s}` },
  });
  expect(site.status()).toBe(201);
  const siteId = ((await site.json()) as { id: string }).id;
  const visible = await act(
    admin.page,
    await create(admin.page, { title: `E2E Visible ${s}` }),
    'publish',
  );
  const hidden = {
    draft: await create(admin.page, { title: `E2E Draft ${s}` }),
    archived: await act(
      admin.page,
      await act(admin.page, await create(admin.page, { title: `E2E Archived ${s}` }), 'publish'),
      'archive',
    ),
    otherSite: await act(
      admin.page,
      await create(admin.page, {
        title: `E2E Other site ${s}`,
        audience: 'sites',
        site_ids: [siteId],
      }),
      'publish',
    ),
    scheduled: await act(
      admin.page,
      await create(admin.page, {
        title: `E2E Later ${s}`,
        publish_from: new Date(Date.now() + 3_600_000).toISOString(),
      }),
      'publish',
    ),
  };
  const requester = await openSeeded(browser, 'arabic', `${PORTAL_URL}/`);
  try {
    // The portal home and its banners: only the live one for everyone.
    await expect(requester.page.getByTestId(`portal-announcement-${visible.id}`)).toBeVisible(LIVE);
    for (const item of Object.values(hidden)) {
      await expect(requester.page.getByText(item.title)).toHaveCount(0);
    }
    // The API: the feed, each record by ID (404, never 403), the staff list (403).
    const feed = (await (await call(requester.page, 'GET', '/announcements/feed')).json()) as {
      items: Item[];
    };
    const feedIds = feed.items.map((i) => i.id);
    expect(feedIds).toContain(visible.id);
    for (const [name, item] of Object.entries(hidden)) {
      expect(feedIds, name).not.toContain(item.id);
      const byId = await call(requester.page, 'GET', `/announcements/${item.id}`);
      expect(byId.status(), name).toBe(404);
      // Realtime: not even the record's channel.
      const token = await call(requester.page, 'POST', '/realtime/subscription-token', {
        body: { channel: `t:${await tenantOf(requester.page)}:announcement:${item.id}` },
      });
      expect(token.status(), name).toBe(403);
    }
    expect((await call(requester.page, 'GET', `/announcements/${visible.id}`)).status()).toBe(200);
    expect((await call(requester.page, 'GET', '/announcements')).status()).toBe(403);

    // In Arabic, right to left, labelled (no raw codes) and accessible.
    await expect(requester.page.locator('html')).toHaveAttribute('dir', 'rtl');
    const text = (await requester.page.getByTestId('portal-announcements').textContent()) ?? '';
    expect(text).not.toMatch(/\b(info|warning|critical|published|live|everyone)\b/);
    await expectAccessible(requester.page, 'portal home with announcements (Arabic, RTL)');
    await requester.page.screenshot({ path: 'test-results/portal-announcements-ar.png' });
  } finally {
    await trash(admin.page, [visible.id, ...Object.values(hidden).map((i) => i.id)]);
    await Promise.all([admin.context.close(), requester.context.close()]);
  }
});

async function tenantOf(page: Page): Promise<string> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    tenant: { id: string };
  };
  return me.tenant.id;
}

test('site-scoped technician: sees and writes only announcements for their site', async ({
  browser,
}) => {
  const admin = await open(browser, 'admin', '/announcements');
  await deleteE2eRoles(admin.page); // left by an interrupted earlier run
  const s = stamp();
  const site = (await (
    await call(admin.page, 'POST', '/organization/sites', { body: { name: `E2E Site North ${s}` } })
  ).json()) as { id: string };
  const role = await call(admin.page, 'POST', '/roles', {
    body: {
      name: `E2E Site announcer ${s}`,
      permissions: [
        { permission: 'announcements.view', scope: 'site' },
        { permission: 'announcements.manage', scope: 'site' },
        { permission: 'sites.view', scope: 'all' },
      ],
    },
  });
  expect(role.status(), await role.text()).toBe(201);
  const users = (await (
    await call(
      admin.page,
      'GET',
      `/users?filter=${encodeURIComponent(JSON.stringify({ field: 'email', op: 'eq', value: USERS.limited.email }))}`,
    )
  ).json()) as { items: { id: string }[] };
  const limitedId = users.items[0]?.id ?? '';
  const roleId = ((await role.json()) as { id: string }).id;
  expect((await call(admin.page, 'PUT', `/users/${limitedId}/roles/${roleId}`)).status()).toBe(204);
  expect(
    (await call(admin.page, 'PUT', `/organization/sites/${site.id}/members/${limitedId}`)).status(),
  ).toBe(204);
  const forNorth = await create(admin.page, {
    title: `E2E North ${s}`,
    audience: 'sites',
    site_ids: [site.id],
  });
  const forAll = await create(admin.page, { title: `E2E Everyone ${s}` });
  const limited = await open(browser, 'limited', '/announcements');
  try {
    await expect(limited.page.getByText(forNorth.title)).toBeVisible();
    await expect(limited.page.getByText(forAll.title)).toHaveCount(0);
    expect((await call(limited.page, 'GET', `/announcements/${forAll.id}`)).status()).toBe(404);
    // Writing outside the site is refused; inside it works.
    const outside = await call(limited.page, 'POST', '/announcements', {
      body: { title: `E2E Outside ${s}`, body: 'x' },
    });
    expect(outside.status()).toBe(403);
    const inside = await create(limited.page, {
      title: `E2E Inside ${s}`,
      audience: 'sites',
      site_ids: [site.id],
    });
    // Live: the admin's new North announcement appears in the scoped list by itself.
    const later = await create(admin.page, {
      title: `E2E North later ${s}`,
      audience: 'sites',
      site_ids: [site.id],
    });
    await expect(limited.page.getByText(later.title)).toBeVisible(LIVE);
    await trash(admin.page, [inside.id, later.id]);
  } finally {
    await trash(admin.page, [forNorth.id, forAll.id]);
    await call(admin.page, 'DELETE', `/organization/sites/${site.id}/members/${limitedId}`);
    await deleteE2eRoles(admin.page);
    await Promise.all([admin.context.close(), limited.context.close()]);
  }
});

test('tenant isolation: another company never sees Demo Company’s announcements', async ({
  browser,
}) => {
  const admin = await open(browser, 'admin', '/announcements');
  const item = await act(
    admin.page,
    await create(admin.page, { title: `E2E Demo only ${stamp()}` }),
    'publish',
  );
  const other = await openSeeded(browser, 'other', '/');
  try {
    expect((await call(other.page, 'GET', `/announcements/${item.id}`)).status()).toBe(404);
    const feed = (await (await call(other.page, 'GET', '/announcements/feed')).json()) as {
      items: Item[];
    };
    expect(feed.items.map((i) => i.id)).not.toContain(item.id);
    await expect(other.page.getByTestId(`announcement-banner-${item.id}`)).toHaveCount(0);
  } finally {
    await trash(admin.page, [item.id]);
    await Promise.all([admin.context.close(), other.context.close()]);
  }
});

test('announcements screens are labelled and accessible in light, dark and Arabic (RTL)', async ({
  browser,
}) => {
  const admin = await open(browser, 'admin', '/announcements');
  const item = await create(admin.page, {
    title: `E2E Accessible ${stamp()}`,
    severity: 'warning',
  });
  try {
    await admin.page.reload();
    await expect(admin.page.getByTestId(`ann-row-${item.display_id}`)).toBeVisible();
    await expectAccessible(admin.page, 'announcements list (light)');
    await admin.page.getByTestId(`ann-row-${item.display_id}`).click();
    await expect(admin.page.getByTestId('ann-heading')).toBeVisible();
    await expectAccessible(admin.page, 'announcement (light)');

    await admin.page.getByTestId('appearance-menu').click();
    await admin.page.getByText('Dark', { exact: true }).click();
    await admin.page.getByTestId('language-select').click();
    await admin.page.locator('.ant-select-item-option[title="العربية"]').click();
    await admin.page.keyboard.press('Escape');
    await expect(admin.page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(admin.page.getByTestId('ann-status')).toHaveText('مسودة');
    const body = (await admin.page.locator('main, #main').first().textContent()) ?? '';
    expect(body).not.toMatch(/not_from_status|no_permission|announcement_|\bdraft\b|\bwarning\b/);
    await expectAccessible(admin.page, 'announcement (Arabic, dark)');
    await admin.page.goto('/announcements');
    await expect(admin.page.getByTestId(`ann-row-${item.display_id}`)).toBeVisible();
    await expectAccessible(admin.page, 'announcements list (Arabic, dark)');
    await admin.page.screenshot({ path: 'test-results/announcements-ar-dark.png', fullPage: true });
  } finally {
    await trash(admin.page, [item.id]);
    await admin.context.close();
  }
});
