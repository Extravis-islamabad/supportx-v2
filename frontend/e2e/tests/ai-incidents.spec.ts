import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

// WP-038, AI on incidents, against the stack's recorded fake model (CI never runs a real one):
// the conversation summary (REQ-INC-137), possible duplicates while writing (REQ-INC-022,
// D-134) and writing help in the reply editor (REQ-INC-136). Accessible, and right to left in
// Arabic. Every record made here is deleted afterwards.

const LIVE = { timeout: 15_000 };

interface Me {
  csrf_token: string;
  user: { id: string };
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

async function incident(page: Page, subject: string): Promise<{ id: string; version: number }> {
  const { csrf_token, user } = await me(page);
  const made = await page.request.post('/api/v1/incidents', {
    data: { subject, requester_id: user.id, description: `<p>${subject}</p>` },
    headers: { 'X-CSRF-Token': csrf_token },
  });
  expect(made.status(), await made.text()).toBe(201);
  return (await made.json()) as { id: string; version: number };
}

async function remove(page: Page, id: string): Promise<void> {
  const { csrf_token } = await me(page);
  const found = await page.request.get(`/api/v1/incidents/${id}`);
  if (found.status() !== 200) return;
  const { version } = (await found.json()) as { version: number };
  await page.request.delete(`/api/v1/incidents/${id}`, {
    headers: { 'If-Match': `"${String(version)}"`, 'X-CSRF-Token': csrf_token },
  });
}

async function language(page: Page, ui_locale: string | null): Promise<void> {
  const { csrf_token, user } = await me(page);
  const path = `/api/v1/users/${user.id}`;
  const { version } = (await (await page.request.get(path)).json()) as { version: number };
  const saved = await page.request.patch(path, {
    data: { ui_locale },
    headers: { 'If-Match': `"${String(version)}"`, 'X-CSRF-Token': csrf_token },
  });
  expect(saved.status(), await saved.text()).toBe(200);
}

test('the conversation summary: made on request, marked as AI-written, in English and Arabic', async ({
  page,
}) => {
  await signInAs(page, 'tech', '/incidents');
  const item = await incident(
    page,
    `E2E summary ${String(Date.now())} Outlook asks for a password`,
  );
  try {
    await page.goto(`/incidents/${item.id}`);
    const card = page.getByTestId('ai-summary');
    await expect(card.getByTestId('ai-summary-empty')).toBeVisible();
    await card.getByTestId('ai-summary-refresh').click();
    await expect(card.getByTestId('ai-summary-text')).toContainText('[conversation_summary]', LIVE);
    await expect(card).toContainText('Written by AI');
    await expectAccessible(page, 'incident with its summary');
    await language(page, 'ar');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('ai-summary')).toContainText('ملخص المحادثة');
    await expectAccessible(page, 'incident with its summary (Arabic)');
  } finally {
    await language(page, null);
    await remove(page, item.id);
  }
});

test('possible duplicates appear beside the new-incident form', async ({ page }) => {
  await signInAs(page, 'tech', '/incidents');
  const words = `E2E duplicate ${String(Date.now())} VPN drops every hour in Lahore`;
  const first = await incident(page, words);
  try {
    await page.goto('/incidents/new');
    await page.getByTestId('inc-subject').fill(words);
    // By meaning once the indexing worker has embedded the first one, by subject meanwhile:
    // either way it is offered.
    await expect(page.getByTestId('inc-duplicates')).toBeVisible(LIVE);
    await expect(page.getByTestId('inc-duplicates')).toContainText(words);
    await expectAccessible(page, 'new incident with possible duplicates');
  } finally {
    await remove(page, first.id);
  }
});

test('writing help drafts a reply that is inserted only after review', async ({ page }) => {
  await signInAs(page, 'tech', '/incidents');
  const item = await incident(page, `E2E writing ${String(Date.now())} Printer jams on floor 3`);
  try {
    await page.goto(`/incidents/${item.id}`);
    await page.getByRole('tab', { name: /Conversation/ }).click();
    await page.getByTestId('conv-reply').locator('button').first().click();
    await page.getByTestId('writing-help-open').first().click();
    const drawer = page.getByTestId('writing-help');
    await drawer.getByTestId('writing-help-instruction').fill('Say we are checking the printer');
    await drawer.getByTestId('writing-help-ask').click();
    await expect(drawer.getByTestId('writing-help-text')).toContainText('[reply_draft]', LIVE);
    await expectAccessible(page, 'writing help with a suggestion');
    // Nothing reaches the editor (or the requester) until Insert.
    await expect(page.getByTestId('conv-editor')).not.toContainText('[reply_draft]');
    await drawer.getByTestId('writing-help-insert').click();
    await expect(page.getByTestId('conv-editor')).toContainText('[reply_draft]', LIVE);
  } finally {
    await remove(page, item.id);
  }
});
