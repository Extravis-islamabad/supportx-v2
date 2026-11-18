import { expect, test } from '@playwright/test';

import { FAKE, mockErasures, mockPeopleList } from './erasureMocks';
import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * ADR-052 erasure screens on a mocked erasure API only (the coordinator's condition 2): every
 * erasure call and every person named is answered in the browser (erasureMocks.ts), so nothing
 * is requested, redacted or approved on any server. Sign-in is the suite's own admin.
 */
test('erasure: ask, review the report, redact, approve (mocked API)', async ({ page }) => {
  test.setTimeout(120_000);
  const mock = await mockErasures(page, { exists: false });
  await mockPeopleList(page);

  // Ask: from the made-up person's drawer.
  await signInAs(page, 'admin', '/admin/users');
  await page.getByText('Noor Hassan').first().click();
  const drawer = page.getByTestId('person-drawer');
  await drawer.getByRole('tab', { name: 'Privacy' }).click();
  await drawer.getByTestId('person-erasure-ask').click();
  const ask = page.getByTestId('erasure-request');
  await expect(ask.getByTestId('erasure-request-submit')).toBeDisabled();
  await ask.getByTestId('erasure-request-reason').click();
  await page.getByTitle('The person asked').click();
  await ask.getByTestId('erasure-request-successor').click();
  await page.keyboard.type('Samir');
  await page.getByRole('option', { name: /Samir Khan/ }).click();
  await ask.getByTestId('erasure-request-name').fill('Noor Hassan');
  await expectAccessible(page, 'erasure request');
  await ask.getByTestId('erasure-request-submit').click();
  await expect(ask).toHaveCount(0);
  expect(mock.calls).toContain(`POST /people/${FAKE.person}/erasure`);

  // The record: review, redact one mention, approve with the name typed.
  await page.goto(`/admin/erasures/${FAKE.erasure}`);
  const record = page.getByTestId('erasure-page');
  await expect(record.getByTestId('erasure-approve')).toBeDisabled();
  await expect(record.getByTestId('erasure-approve-why')).toContainText('Review the report');
  await record.locator('[data-node-key="mentions"] [role="tab"]').click();
  await expect(page.getByTestId('erasure-report-table')).toContainText('Tickets');
  await page.getByTestId(`erasure-passage-${FAKE.mention}`).click();
  await expect(page.getByTestId('erasure-passage-text').locator('mark')).toHaveText('Noor Hassan');
  await expectAccessible(page, 'erasure passage');
  await page.getByTestId('erasure-passage-close').click();
  await expect(page.getByTestId('erasure-passage-text')).toHaveCount(0);
  await page.getByTestId('erasure-mark-reviewed').click();
  await expect(page.getByTestId('erasure-reviewed')).toBeVisible();
  await page.getByLabel('Select this mention').check();
  await page.getByTestId('erasure-redact').click();
  await page.locator('#erasure-redact-ok').click();
  await expect(page.getByTestId('erasure-mentions-table')).toContainText('Removed');
  await expectAccessible(page, 'erasure mentions');

  await record.getByTestId('erasure-approve').click();
  const approve = page.getByTestId('erasure-approve-dialog');
  await expect(approve.getByTestId('erasure-holdings')).toContainText('Assets they still hold');
  await approve.getByTestId('erasure-approve-name').fill('Noor Hasan');
  await expect(approve.getByTestId('erasure-approve-ok')).toBeDisabled();
  await approve.getByTestId('erasure-approve-name').fill('Noor Hassan');
  await approve.getByTestId('erasure-approve-ok').click();
  await expect(record.getByTestId('erasure-state')).toHaveText('Approved');
  expect(mock.calls).toContain(`POST /erasures/${FAKE.erasure}/approve`);
  expect(mock.calls).toContain(`POST /erasures/${FAKE.erasure}/mentions/redact`);
});

test('erasure screens in Arabic read right to left, in labels (mocked API)', async ({ page }) => {
  test.setTimeout(120_000);
  await mockErasures(page, { reviewed: true });
  await signInAs(page, 'admin');
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  const path = `/api/v1/users/${me.user.id}`;
  const user = (await (await page.request.get(path)).json()) as { version: number };
  const done = await page.request.patch(path, {
    data: { ui_locale: 'ar' },
    headers: { 'If-Match': `"${String(user.version)}"`, 'X-CSRF-Token': me.csrf_token },
  });
  expect(done.status(), await done.text()).toBe(200);
  try {
    await page.goto(`/admin/erasures/${FAKE.erasure}`);
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    const record = page.getByTestId('erasure-page');
    await expect(record.getByTestId('erasure-state')).toHaveText('بانتظار الاعتماد');
    await record.locator('[data-node-key="mentions"] [role="tab"]').click();
    const table = page.getByTestId('erasure-report-table');
    await expect(table).toContainText('التذاكر');
    await expect(table).not.toContainText('work_items');
    await expectAccessible(page, 'erasure mentions (ar)');
  } finally {
    await resetLanguage(page);
  }
});
