import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

/**
 * WP-034 session 1 (D-125): an article published in a suite-owned topic is found from the
 * command palette, voted on by a technician (the editor's Feedback tab counts it live), and
 * suggested while the technician types a new incident's subject, in a column that never moves
 * the form (REQ-WI-012). axe on the form with suggestions and on the article page.
 *
 * Suite-owned data only: an "E2E" topic and article, deleted afterwards. Runs under the QA lock
 * on the shared stack from main.
 */

const LIVE = { timeout: 5_000 };

async function csrf(page: Page): Promise<string> {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  return me.csrf_token;
}

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const headers: Record<string, string> = { 'X-CSRF-Token': await csrf(page) };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function open(browser: Browser, path: string, as: 'admin' | 'tech') {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, as, path);
  return { context, page };
}

interface Draft {
  drafts: Record<string, { version: number }>;
}

/** The technician writes and submits; the admin approves: a published article. */
async function publish(tech: Page, admin: Page, topic: string, title: string): Promise<string> {
  const made = await call(tech, 'POST', '/knowledge/articles', {
    topic_id: topic,
    type_code: 'troubleshooting',
    title,
    body_html: '<p>Open the printer tray, take the sheet out slowly and restart the spooler.</p>',
    keywords: ['printer', 'jam'],
  });
  expect(made.status(), await made.text()).toBe(201);
  const id = ((await made.json()) as { id: string }).id;
  const draft = async (page: Page) =>
    ((await (await call(page, 'GET', `/knowledge/articles/${id}`)).json()) as Draft).drafts.en
      ?.version;
  const submitted = await call(
    tech,
    'POST',
    `/knowledge/articles/${id}/drafts/en/submit`,
    { note: 'Ready' },
    await draft(tech),
  );
  expect(submitted.status(), await submitted.text()).toBe(200);
  const approved = await call(
    admin,
    'POST',
    `/knowledge/articles/${id}/drafts/en/approve`,
    undefined,
    await draft(admin),
  );
  expect(approved.status(), await approved.text()).toBe(200);
  return id;
}

test('palette, vote with live feedback, suggestions beside a form that never moves (en)', async ({
  browser,
}) => {
  const admin = await open(browser, '/knowledge', 'admin');
  const tech = await open(browser, '/', 'tech');
  const tag = Date.now().toString(36);
  const topic = await call(admin.page, 'POST', '/knowledge/topics', {
    names: { en: `E2E Printers ${tag}`, ar: `طابعات E2E ${tag}` },
    tech_all: true,
  });
  expect(topic.status(), await topic.text()).toBe(201);
  const topicId = ((await topic.json()) as { id: string }).id;
  const title = `E2E clear a printer jam ${tag}`;
  let articleId: string | undefined;
  try {
    articleId = await publish(tech.page, admin.page, topicId, title);

    // The palette finds it (REQ-KB-053) and opens it.
    await tech.page.keyboard.press('Control+k');
    // Inside the palette's dialog: the home page has comboboxes of its own (dashboard selects).
    const palette = tech.page.getByRole('dialog');
    await palette.getByRole('combobox').fill(`printer jam ${tag}`);
    await palette.getByText(title, { exact: false }).first().click();
    await expect(tech.page).toHaveURL(new RegExp(`/knowledge/articles/${articleId}$`), LIVE);

    // The editor's Feedback tab counts the technician's vote live (REQ-KB-069 AC4).
    await admin.page.goto(`/knowledge/articles/${articleId}`);
    await admin.page.getByRole('tab', { name: 'Feedback' }).click();
    await expect(admin.page.getByTestId('kb-feedback-score')).toContainText('No votes yet', LIVE);
    await tech.page.getByTestId('kb-vote-yes').click();
    await expect(tech.page.getByTestId('kb-vote-done')).toBeVisible(LIVE);
    await expect(admin.page.getByTestId('kb-feedback-score')).toContainText('1 of 1', LIVE);
    await expectAccessible(tech.page, 'article page with the vote');

    // Suggestions while typing (REQ-INC-021), in a column that never moves the form.
    await tech.page.goto('/incidents/new');
    const form = tech.page.getByTestId('inc-form');
    await expect(tech.page.getByTestId('kb-suggestions')).toBeVisible(LIVE);
    const before = await form.boundingBox();
    await tech.page.getByTestId('inc-subject').fill(`printer jam ${tag}`);
    await expect(tech.page.getByTestId(`kb-suggestion-${articleId}`)).toBeVisible(LIVE);
    const after = await form.boundingBox();
    expect(after?.x).toBe(before?.x);
    expect(after?.width).toBe(before?.width);
    await expectAccessible(tech.page, 'new incident with suggestions');
  } finally {
    if (articleId !== undefined) {
      const found = await call(admin.page, 'GET', `/knowledge/articles/${articleId}`);
      if (found.status() === 200) {
        const { version } = (await found.json()) as { version: number };
        await call(admin.page, 'DELETE', `/knowledge/articles/${articleId}`, undefined, version);
      }
    }
    const topics = (await (await call(admin.page, 'GET', '/knowledge/topics')).json()) as {
      id: string;
      version: number;
    }[];
    const row = topics.find((t) => t.id === topicId);
    if (row !== undefined) {
      await call(admin.page, 'DELETE', `/knowledge/topics/${topicId}`, undefined, row.version);
    }
    await admin.context.close();
    await tech.context.close();
  }
});
