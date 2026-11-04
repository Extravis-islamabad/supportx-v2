import { expect, test, type Browser, type Page } from '@playwright/test';

import { SEEDED } from '../stack';
import { expectAccessible, resetLanguage, signIn, signInAs } from './helpers';

/**
 * WP-033 knowledge, sessions 2, 3a and 3b in one round (D-120 (1)), English and Arabic:
 * an author writes an article with a callout and an inline image and submits it; in a second
 * browser the approver's count rises live, the inbox previews it and approves it, and the
 * author's page turns "Published" live. Sending back shows the reason; withdrawing takes the
 * article away from an open reader live; a technician outside the topic's group never sees it
 * (list, search, inbox, URL). Admin › Knowledge: a new prefix continues the numbering. axe on
 * every knowledge screen at 1366 and 390 px.
 *
 * Suite-owned data only: an "E2E" group and topic, articles moved to the trash, the prefix put
 * back. Runs under the QA lock on the shared stack from main.
 */

const LIVE = { timeout: 5_000 };
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
);

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

async function open(browser: Browser, path: string, as: 'admin' | 'tech' | 'limited' | 'outsider') {
  const context = await browser.newContext();
  const page = await context.newPage();
  if (as === 'outsider') await signIn(page, SEEDED.tech.email, SEEDED.tech.password, path);
  else await signInAs(page, as, path);
  return { context, page };
}

const stamp = () => Date.now().toString(36);

interface World {
  group: string;
  topic: string;
  techId: string;
  articles: string[];
}

/** An E2E group with the suite technician in it, and a topic only that group sees. */
async function world(admin: Page, tech: Page, tag: string): Promise<World> {
  const techId = (await me(tech)).user.id;
  const group = await call(admin, 'POST', '/organization/groups', { name: `E2E KB ${tag}` });
  expect(group.status(), await group.text()).toBe(201);
  const groupId = ((await group.json()) as { id: string }).id;
  expect([200, 204]).toContain(
    (await call(admin, 'PUT', `/organization/groups/${groupId}/members/${techId}`)).status(),
  );
  const topic = await call(admin, 'POST', '/knowledge/topics', {
    names: { en: `E2E Topic ${tag}`, ar: `موضوع E2E ${tag}` },
    tech_all: false,
    tech_groups: [groupId],
  });
  expect(topic.status(), await topic.text()).toBe(201);
  return {
    group: groupId,
    topic: ((await topic.json()) as { id: string }).id,
    techId,
    articles: [],
  };
}

async function cleanUp(admin: Page, made: World | undefined): Promise<void> {
  if (made === undefined) return;
  for (const id of made.articles) {
    const found = await call(admin, 'GET', `/knowledge/articles/${id}`);
    if (found.status() === 200) {
      const { version } = (await found.json()) as { version: number };
      await call(admin, 'DELETE', `/knowledge/articles/${id}`, undefined, version);
    }
  }
  const topic = await call(admin, 'GET', '/knowledge/topics');
  const row = ((await topic.json()) as { id: string; version: number }[]).find(
    (t) => t.id === made.topic,
  );
  if (row !== undefined) {
    await call(admin, 'DELETE', `/knowledge/topics/${made.topic}`, undefined, row.version);
  }
  await call(admin, 'DELETE', `/organization/groups/${made.group}/members/${made.techId}`);
}

/** Paste an image file into the editor, as a person would (uploaded as an inline image). */
async function pasteImage(page: Page, testId: string): Promise<void> {
  const editor = page.getByTestId(testId);
  await editor.click();
  await editor.evaluate((element, bytes) => {
    const file = new File([new Uint8Array(bytes)], 'diagram.png', { type: 'image/png' });
    const data = new DataTransfer();
    data.items.add(file);
    element.dispatchEvent(
      new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }),
    );
  }, Array.from(PNG));
}

/** The author writes an article in the topic through the editor and submits it with a note. */
async function writeAndSubmit(page: Page, made: World, title: string): Promise<string> {
  await page.goto(`/knowledge/articles/new?topic=${made.topic}`);
  await page.getByTestId('kb-title').fill(title);
  await page.getByTestId('kb-create').click();
  await expect(page).toHaveURL(/\/knowledge\/articles\/[0-9a-f-]{36}\/edit\/en$/, LIVE);
  const id = page.url().split('/').at(-3) ?? '';
  made.articles.push(id);
  const body = page.getByTestId('kb-edit-body');
  await body.click();
  await page.keyboard.type('Open the portal and reset the token.');
  await page.getByTestId('rt-callout').click();
  await page.keyboard.type('Keep the old token until the new one works.');
  await pasteImage(page, 'kb-edit-body');
  await expect(body.locator('img')).toHaveCount(1, LIVE);
  // The state, not its words ("All changes saved" in English; the Arabic run reads the same).
  await expect(page.getByTestId('kb-save-state')).toHaveAttribute('data-state', 'saved', LIVE);
  await page.getByTestId('kb-done').click();
  await expect(page).toHaveURL(new RegExp(`/knowledge/articles/${id}$`), LIVE);
  await page.getByTestId('kb-action-submit').click();
  await page.getByTestId('kb-step-text').fill('Ready for review');
  await page.locator('.ant-modal:visible').getByRole('button').last().click();
  await expect(page.getByTestId('kb-status').first()).toContainText('In review', LIVE);
  return id;
}

test('write, approve live from the inbox, send back, withdraw; an outsider never sees it (en)', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const tag = stamp();
  const admin = await open(browser, '/knowledge', 'admin');
  const author = await open(browser, '/knowledge', 'tech');
  const outsider = await open(browser, '/knowledge', 'outsider');
  let made: World | undefined;
  try {
    made = await world(admin.page, author.page, tag);
    const count = admin.page.getByTestId('kb-open-inbox');
    const before = Number((await count.innerText()).replace(/\D/g, '') || '0');

    // 1. Write and submit: the approver's count rises live in the other browser.
    const first = await writeAndSubmit(author.page, made, `E2E VPN token ${tag}`);
    await expect(count).toContainText(String(before + 1), LIVE);

    // 2. The inbox previews it beside "nothing published yet", image included; approve.
    await count.click();
    await expect(admin.page).toHaveURL(/\/knowledge\/approvals/);
    await admin.page.getByText(`E2E VPN token ${tag}`).click();
    const preview = admin.page.getByTestId('kb-inbox-preview');
    await expect(preview.getByTestId('kb-inbox-first')).toBeVisible();
    await expect(preview.getByTestId('kb-inbox-note')).toContainText('Ready for review');
    await expect(preview.getByTestId('kb-inbox-review-body').locator('img')).toHaveCount(1);
    await expectAccessible(admin.page, 'approval inbox');
    await preview.getByTestId('kb-action-approve').click();
    // The author's open page turns "Published" with no reload.
    await expect(author.page.getByTestId('kb-status').first()).toContainText('Published', LIVE);
    await expectAccessible(author.page, 'article page');

    // 3. A second article sent back: the author sees the reason on the draft.
    const second = await writeAndSubmit(author.page, made, `E2E Printer ${tag}`);
    await admin.page.goto(`/knowledge/approvals?article=${second}`);
    await admin.page.getByTestId('kb-action-reject').click();
    await admin.page.getByTestId('kb-step-text').fill('Add the model numbers');
    await admin.page.locator('.ant-modal:visible').getByRole('button').last().click();
    await expect(author.page.getByTestId('kb-reject-reason')).toContainText(
      'Add the model numbers',
      LIVE,
    );

    // 4. The outsider (not in the topic's group) sees it nowhere: list, search, inbox, URL.
    await outsider.page.goto(`/knowledge?q=${encodeURIComponent(`E2E VPN token ${tag}`)}`);
    await expect(outsider.page.getByTestId('kb-table')).toBeVisible();
    await expect(outsider.page.getByText(`E2E VPN token ${tag}`)).toHaveCount(0);
    await outsider.page.goto(`/knowledge/articles/${first}`);
    await expect(outsider.page.getByTestId('kb-heading')).toHaveCount(0);
    await expect(outsider.page.getByText(`E2E VPN token ${tag}`)).toHaveCount(0);
    const direct = await outsider.page.request.get(`/api/v1/knowledge/articles/${first}`);
    expect(direct.status()).toBe(404);

    // 5. Withdraw: the author, reading the published article, gets "no longer available" live.
    await author.page.goto(`/knowledge/articles/${first}`);
    await expect(author.page.getByTestId('kb-heading')).toContainText(`E2E VPN token ${tag}`);
    await admin.page.goto(`/knowledge/articles/${first}`);
    await admin.page.getByTestId('kb-action-withdraw').click();
    await admin.page.getByTestId('kb-step-text').fill('Replaced by the new portal guide');
    await admin.page.locator('.ant-modal:visible').getByRole('button').last().click();
    await expect(author.page.getByTestId('kb-withdrawn')).toBeVisible(LIVE);
  } finally {
    await cleanUp(admin.page, made);
    for (const one of [admin, author, outsider]) await one.context.close();
  }
});

test('Admin › Knowledge: a new prefix continues the numbering; the screens pass axe at 1366 and 390 px', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const tag = stamp();
  const admin = await open(browser, '/admin/knowledge', 'admin');
  const author = await open(browser, '/knowledge', 'tech');
  let made: World | undefined;
  let original: { prefix: string; version: number } | undefined;
  try {
    made = await world(admin.page, author.page, tag);
    const settings = (await (await call(admin.page, 'GET', '/knowledge/settings')).json()) as {
      prefix: string;
      next_number: number;
      version: number;
    };
    original = { prefix: settings.prefix, version: settings.version };
    const card = admin.page.getByTestId('kb-admin-general');
    await card.getByTestId('kb-admin-prefix').fill('KBE');
    await expect(card.getByTestId('kb-admin-next-id')).toContainText(
      `KBE-${String(settings.next_number)}`,
    );
    await card.getByTestId('kb-admin-save').click();
    await expect(admin.page.getByText('Saved.', { exact: false })).toBeVisible(LIVE);
    original.version += 1;

    const created = await call(author.page, 'POST', '/knowledge/articles', {
      topic_id: made.topic,
      type_code: 'how_to',
      title: `E2E numbering ${tag}`,
    });
    expect(created.status(), await created.text()).toBe(201);
    const article = (await created.json()) as { id: string; display_id: string };
    made.articles.push(article.id);
    expect(article.display_id).toBe(`KBE-${String(settings.next_number)}`); // continues

    for (const size of [
      { width: 1366, height: 900 },
      { width: 390, height: 844 },
    ]) {
      for (const page of [admin.page, author.page]) await page.setViewportSize(size);
      await admin.page.goto('/admin/knowledge');
      await expect(admin.page.getByTestId('kb-admin-types')).toBeVisible();
      await expectAccessible(admin.page, `knowledge settings ${String(size.width)}`);
      await author.page.goto('/knowledge');
      await expect(author.page.getByTestId('kb-table')).toBeVisible();
      await expectAccessible(author.page, `knowledge home ${String(size.width)}`);
      await author.page.goto(`/knowledge/articles/${article.id}/edit/en`);
      await expect(author.page.getByTestId('kb-edit-body')).toBeVisible();
      await expectAccessible(author.page, `article editor ${String(size.width)}`);
      await admin.page.goto('/knowledge/approvals');
      await expect(admin.page.getByTestId('kb-inbox-queue')).toBeVisible();
      await expectAccessible(admin.page, `approval inbox ${String(size.width)}`);
    }
  } finally {
    if (original !== undefined) {
      await call(
        admin.page,
        'PATCH',
        '/knowledge/settings',
        { prefix: original.prefix },
        original.version,
      );
    }
    await cleanUp(admin.page, made);
    await admin.context.close();
    await author.context.close();
  }
});

test('knowledge in Arabic: right to left, labels only, accessible', async ({ browser }) => {
  test.setTimeout(180_000);
  const tag = stamp();
  const admin = await open(browser, '/knowledge', 'admin');
  const author = await open(browser, '/knowledge', 'tech');
  let made: World | undefined;
  try {
    made = await world(admin.page, author.page, tag);
    const self = await me(admin.page);
    const user = (await (await admin.page.request.get(`/api/v1/users/${self.user.id}`)).json()) as {
      version: number;
    };
    const arabic = await call(
      admin.page,
      'PATCH',
      `/users/${self.user.id}`,
      { ui_locale: 'ar' },
      user.version,
    );
    expect(arabic.status(), await arabic.text()).toBe(200);
    await writeAndSubmit(author.page, made, `E2E عربي ${tag}`);

    for (const path of ['/knowledge', '/knowledge/approvals', '/admin/knowledge']) {
      await admin.page.goto(path);
      await expect(admin.page.locator('html')).toHaveAttribute('dir', 'rtl');
      const text = await admin.page.locator('main').innerText();
      expect(text).not.toMatch(/knowledge\.|kb_view\.|kb_type\.|in_review|how_to/);
      await expectAccessible(admin.page, `${path} (Arabic)`);
    }
    await admin.page.goto('/knowledge/approvals');
    await admin.page.getByText(`E2E عربي ${tag}`).click();
    await expect(admin.page.getByTestId('kb-inbox-preview')).toBeVisible();
    await expect(admin.page.getByTestId('kb-inbox-queue')).toContainText('بانتظارك');
  } finally {
    await resetLanguage(admin.page);
    await cleanUp(admin.page, made);
    await admin.context.close();
    await author.context.close();
  }
});

/** An article in the topic, written by the technician and approved by the admin (published). */
async function publish(admin: Page, tech: Page, topic: string, title: string): Promise<string> {
  const created = await call(tech, 'POST', '/knowledge/articles', {
    topic_id: topic,
    type_code: 'how_to',
    title,
    body_html: '<p>Open the portal and reset the token.</p>',
  });
  expect(created.status(), await created.text()).toBe(201);
  const article = (await created.json()) as { id: string; drafts: { en: { version: number } } };
  const submitted = await call(
    tech,
    'POST',
    `/knowledge/articles/${article.id}/drafts/en/submit`,
    { note: 'Ready' },
    article.drafts.en.version,
  );
  expect(submitted.status(), await submitted.text()).toBe(200);
  const draft = (await submitted.json()) as { version: number };
  const approved = await call(
    admin,
    'POST',
    `/knowledge/articles/${article.id}/drafts/en/approve`,
    undefined,
    draft.version,
  );
  expect(approved.status(), await approved.text()).toBe(200);
  return article.id;
}

test('knowledge in a reply: the server decides the warning, the card shows the link (s4, D-121)', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const tag = stamp();
  const admin = await open(browser, '/knowledge', 'admin');
  const tech = await open(browser, '/knowledge', 'tech');
  const requester = await open(browser, '/', 'limited');
  let made: World | undefined;
  const incidents: string[] = [];
  try {
    made = await world(admin.page, tech.page, tag);
    const forAll = await call(admin.page, 'POST', '/knowledge/topics', {
      names: { en: `E2E Help ${tag}`, ar: `مساعدة E2E ${tag}` },
      requesters: 'all',
    });
    expect(forAll.status(), await forAll.text()).toBe(201);
    const helpTopic = ((await forAll.json()) as { id: string }).id;
    const internal = await publish(admin.page, tech.page, made.topic, `E2E internal ${tag}`);
    const shared = await publish(admin.page, tech.page, helpTopic, `E2E shared ${tag}`);
    made.articles.push(internal, shared);
    const created = await call(tech.page, 'POST', '/incidents', {
      subject: `E2E knowledge ${tag}`,
      requester_id: (await me(requester.page)).user.id,
      group_id: made.group,
    });
    expect(created.status(), await created.text()).toBe(201);
    const incident = ((await created.json()) as { id: string }).id;
    incidents.push(incident);

    await tech.page.goto(`/incidents/${incident}`);
    await tech.page.getByRole('tab', { name: /Conversation/ }).click();
    await tech.page.getByTestId('conv-reply').locator('button').first().click();
    const pickFrom = async (title: string, action: 'content' | 'link') => {
      // The reply editor's picker: the record panel's Knowledge card has its own (D-124).
      await tech.page
        .locator('[data-testid="kb-picker-open"]:not([data-testid="kb-card"] *)')
        .click();
      const drawer = tech.page.getByTestId('kb-picker');
      // The test id is on the <input> itself (Ant's Input.Search passes it down).
      await drawer.getByTestId('kb-picker-search').fill(title);
      const row = drawer.locator('[data-testid^="kb-picker-item-"]').filter({ hasText: title });
      await row.locator(`[data-testid^="kb-picker-${action}-"]`).click();
    };
    // An article the requester cannot read: warned first, and nothing goes in on "Cancel".
    await pickFrom(`E2E internal ${tag}`, 'content');
    await expect(tech.page.getByTestId('kb-picker-warning')).toBeVisible(LIVE);
    await expectAccessible(tech.page, 'knowledge warning');
    await tech.page.locator('.ant-modal:visible').getByRole('button').first().click();
    await expect(tech.page.getByTestId('conv-editor')).not.toContainText('Open the portal');
    // An article the requester can read: no warning, the content goes in at the caret.
    await tech.page.keyboard.press('Escape');
    await pickFrom(`E2E shared ${tag}`, 'content');
    await expect(tech.page.getByTestId('conv-editor')).toContainText('Open the portal', LIVE);
    await expect(tech.page.getByTestId('kb-picker-warning')).toHaveCount(0);
    await tech.page.getByTestId('conv-send').click();
    await expect(
      tech.page.getByTestId('conv-timeline').getByText('Open the portal and reset the token.'),
    ).toBeVisible(LIVE);

    // The incident's Knowledge card shows it, live, as "Used in a reply".
    await tech.page.getByRole('tab', { name: /Details/ }).click();
    const card = tech.page.getByTestId('kb-card');
    await expect(card).toContainText(`E2E shared ${tag}`, LIVE);
    await expect(card).toContainText('Used in a reply');
    await expectAccessible(tech.page, 'incident knowledge card');
    // And the article's Links tab names the incident.
    await tech.page.goto(`/knowledge/articles/${shared}`);
    await tech.page.getByRole('tab', { name: /Links/ }).click();
    await expect(tech.page.getByTestId('kb-links')).toContainText(`E2E knowledge ${tag}`);
  } finally {
    for (const id of incidents) {
      const found = await call(admin.page, 'GET', `/incidents/${id}`);
      if (found.status() === 200) {
        const { version } = (await found.json()) as { version: number };
        await call(admin.page, 'DELETE', `/incidents/${id}`, undefined, version);
      }
    }
    await cleanUp(admin.page, made);
    for (const one of [admin, tech, requester]) await one.context.close();
  }
});
