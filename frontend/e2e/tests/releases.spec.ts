import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

// WP-058a s6, releases on the stage engine (ADR-041): a release made from the console's form
// starts in submission, its rail shows the stages of its path, a move takes it on to planning,
// live; accessible, and right to left in Arabic. Every release made here is deleted afterwards.

const LIVE = { timeout: 15_000 };

interface Me {
  csrf_token: string;
  user: { id: string };
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

async function remove(page: Page, id: string): Promise<void> {
  const { csrf_token } = await me(page);
  const found = await page.request.get(`/api/v1/releases/${id}`);
  if (found.status() !== 200) return;
  const { version } = (await found.json()) as { version: number };
  await page.request.delete(`/api/v1/releases/${id}`, {
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

test('a release is created from its template, moves on its rail, in English and Arabic', async ({
  page,
}) => {
  await signInAs(page, 'admin', '/releases/new');
  let id = '';
  try {
    await expect(page.getByTestId('release-path')).toBeVisible(LIVE); // the template's path
    await page.getByTestId('release-subject').fill(`E2E release ${String(Date.now())}`);
    await page.getByTestId('release-save').click();
    await expect(page.getByTestId('release-page')).toBeVisible(LIVE);
    id = page.url().split('/').at(-1) ?? '';
    await expect(page.getByTestId('rail-submission')).toBeVisible();
    // The rail shows the stage (the header's stage chip is gone, QA fix-round D2).
    await expect(page.getByTestId('release-rail')).toHaveAttribute('data-current', 'submission');
    await expectAccessible(page, 'a new release on its rail');

    await page.getByTestId('move-submission_accepted').click();
    await page.getByTestId('move-ok').click();
    // Accepted completes submission: the release is in planning at once, without a reload.
    await expect(page.getByTestId('release-rail')).toHaveAttribute(
      'data-current',
      'planning',
      LIVE,
    );
    await expect(page.getByTestId('rail-planning')).toContainText('Planning');
    await expect(page.getByTestId('rail-submission-state')).not.toContainText('Not yet');

    await language(page, 'ar');
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('rail-planning')).toContainText('التخطيط', LIVE);
    await expectAccessible(page, 'a release in Arabic');
  } finally {
    await resetLanguage(page);
    if (id !== '') await remove(page, id);
  }
});

test('the releases list shows a new release live, with its stage', async ({ page }) => {
  await signInAs(page, 'admin', '/releases');
  await expect(page.getByTestId('releases-header')).toBeVisible(LIVE);
  const { csrf_token, user } = await me(page);
  const subject = `E2E live release ${String(Date.now())}`;
  const made = await page.request.post('/api/v1/releases', {
    data: { subject, requester_id: user.id },
    headers: { 'X-CSRF-Token': csrf_token, 'Idempotency-Key': crypto.randomUUID() },
  });
  expect(made.status(), await made.text()).toBe(201);
  const { id, display_id } = (await made.json()) as { id: string; display_id: string };
  try {
    // REQ-REL-007 AC3: it appears in the open list without a refresh.
    await expect(page.getByTestId(`release-row-${display_id}`)).toBeVisible(LIVE);
    await expect(page.getByTestId(`release-row-${display_id}`)).toContainText('Submission');
    await expectAccessible(page, 'the releases list');
  } finally {
    await remove(page, id);
  }
});
