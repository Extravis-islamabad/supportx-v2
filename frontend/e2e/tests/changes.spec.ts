import { expect, test, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

// QA flow 4, a change end to end in the console (the change screens): raised from the form for a
// requester, its risk assessed, accepted, planned with a backout plan, approved by the CAB,
// implemented with its outcome, reviewed and closed. Nobody holds the change roles in the e2e
// tenant, so each stage's approval goes to the approval administrators (the admin persona), as
// the panel says. The change made here is moved to the trash afterwards.

const LIVE = { timeout: 15_000 };

interface Me {
  csrf_token: string;
}

async function trash(page: Page, id: string): Promise<void> {
  const { csrf_token } = (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
  const found = await page.request.get(`/api/v1/changes/${id}`);
  if (found.status() !== 200) return;
  const { version } = (await found.json()) as { version: number };
  await page.request.delete(`/api/v1/changes/${id}`, {
    headers: { 'If-Match': `"${String(version)}"`, 'X-CSRF-Token': csrf_token },
  });
}

/** Open a tab and wait until it is the one shown: a click that lands while a dialog is still
 * closing is lost, and the next step would wait on the old tab (nightly 42998307635). */
async function tab(page: Page, name: string): Promise<void> {
  const wanted = page.getByTestId('change-tabs').getByRole('tab', { name, exact: true });
  await expect(async () => {
    await wanted.click();
    await expect(wanted).toHaveAttribute('aria-selected', 'true', { timeout: 2_000 });
  }).toPass(LIVE);
}

// A move's dialog is known by its Move button, never by its form: a move that asks nothing
// (no reason, no fields) has an empty form, which has no size, so "the form is visible" never
// holds and "the form is hidden" holds at once (k3d proof run 43082299609).
const moveOk = (page: Page) => page.getByTestId('move-ok');

/** Confirm the open move and wait until its dialog has gone: the move is saved, the page free. */
async function confirmMove(page: Page): Promise<void> {
  await moveOk(page).click();
  await expect(moveOk(page)).toBeHidden(LIVE);
}

/** The primary move, or one under More, then its dialog's confirm. */
async function moveTo(page: Page, status: string): Promise<void> {
  const button = page.getByTestId('change-moves').getByTestId(`move-${status}`);
  if (!(await button.isVisible())) {
    await page.getByTestId('change-more').click();
  }
  await page.getByTestId(`move-${status}`).first().click();
  await expect(moveOk(page)).toBeVisible(LIVE);
}

/** The one pending approval, approved from the Approvals tab. */
async function approvePending(page: Page): Promise<void> {
  await tab(page, 'Approvals');
  const approve = page.getByTestId('change-approvals').locator('[data-testid$="-approve"]').first();
  await expect(approve).toBeVisible(LIVE);
  await approve.click();
  await page.getByRole('dialog').getByRole('button', { name: 'Approve' }).click();
}

async function stageIs(page: Page, stage: string): Promise<void> {
  await expect(page.getByTestId('change-rail')).toHaveAttribute('data-current', stage, LIVE);
}

test('QA flow 4: raise, assess, accept, plan, CAB, implement, review and close a change', async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signInAs(page, 'admin', '/changes/new');
  let id = '';
  try {
    // Raise it for a requester (never the admin: the requester may not approve, REQ-CHG-039).
    await expect(page.getByTestId('change-path')).toBeVisible(LIVE);
    await page.getByTestId('change-subject').fill(`E2E change ${String(Date.now())}`);
    const requester = page.getByTestId('change-requester');
    await requester.click();
    await requester.locator('input').fill('E2E Limited');
    await page
      .locator('.ant-select-dropdown:visible')
      .getByText(/^Lina E2E Limited$/)
      .first()
      .click();
    await expectAccessible(page, 'a new change');
    await page.getByTestId('change-save').click();

    // It opens on its risk questionnaire: answer every question, the lowest risk each time.
    await expect(page.getByTestId('change-risk')).toBeVisible(LIVE);
    id = page.url().split('/').at(-1)?.split('?')[0] ?? '';
    const groups = page.getByTestId('change-risk').locator('[data-testid^="risk-"]');
    for (const group of await groups.all()) {
      await group.locator('input[type="radio"]').first().check();
    }
    await expect(page.getByTestId('change-risk-level')).toContainText('Low');
    await page.getByTestId('change-risk-save').click();
    await expect(page.getByTestId('change-risk-chip')).toContainText('Low', LIVE);
    await expectAccessible(page, 'the risk questionnaire');

    // Submission: the move says who would approve, then the approval administrators accept.
    await stageIs(page, 'submission');
    await moveTo(page, 'submission_awaiting_acceptance');
    await expect(page.getByTestId('approval-preview')).toBeVisible(LIVE);
    await confirmMove(page);
    await expect(page.getByTestId('change-awaiting-approval')).toBeVisible(LIVE);
    await approvePending(page);
    await stageIs(page, 'planning');

    // Planning: the backout plan first (REQ-CHG-093), then the plan's approval.
    await tab(page, 'Plans');
    await page.getByTestId('plan-backout-add').click();
    await page.getByTestId('plan-backout-editor').click();
    await page.keyboard.type('Restore the saved switch configuration.');
    await page.getByTestId('plan-backout-save').click();
    await expect(page.getByTestId('plan-backout')).toContainText('Restore the saved', LIVE);
    await moveTo(page, 'planning_awaiting_approval');
    await confirmMove(page);
    await approvePending(page);

    // The plan's approval completes planning and raises the CAB review by itself (ADR-041): the
    // administrators approve it (the default board has no members, so they decide).
    await stageIs(page, 'cab_review');
    await approvePending(page);
    await expectAccessible(page, 'the change approvals');

    // The CAB's approval moves it on to implementation, scheduled; then in progress, and its
    // outcome before it completes (REQ-CHG-032).
    await stageIs(page, 'implementation');
    await moveTo(page, 'implementation_in_progress');
    await confirmMove(page);
    await tab(page, 'Schedule');
    await page.getByTestId('outcome-implementation').click();
    await page
      .locator('.ant-select-dropdown:visible')
      .getByText('Successful', { exact: true })
      .click();
    await moveTo(page, 'implementation_implemented');
    await confirmMove(page);
    await stageIs(page, 'review');

    // "Review complete" closes the change in the same move: its dialog asks for the code.
    await moveTo(page, 'review_complete');
    const code = page.getByTestId('move-closure-code');
    await code.click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').first().click();
    await confirmMove(page);
    await stageIs(page, 'closure');
    await expectAccessible(page, 'a closed change');
  } finally {
    await resetLanguage(page);
    if (id !== '') await trash(page, id);
  }
});

test('the changes list shows a new change live, and Pending approval is one of its views', async ({
  page,
}) => {
  await signInAs(page, 'admin', '/changes');
  await expect(page.getByTestId('changes-header')).toBeVisible(LIVE);
  const { csrf_token } = (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { user: { id: string } };
  const made = await page.request.post('/api/v1/changes', {
    data: { subject: `E2E live change ${String(Date.now())}`, requester_id: me.user.id },
    headers: { 'X-CSRF-Token': csrf_token, 'Idempotency-Key': crypto.randomUUID() },
  });
  expect(made.status(), await made.text()).toBe(201);
  const { id, display_id } = (await made.json()) as { id: string; display_id: string };
  try {
    await expect(page.getByTestId(`change-row-${display_id}`)).toBeVisible(LIVE);
    await expect(page.getByTestId(`change-row-${display_id}`)).toContainText('Submission');
    await page.getByTestId('changes-view').click();
    await page.locator('.ant-select-dropdown:visible').getByText('Pending approval').click();
    await expect(page.getByTestId(`change-row-${display_id}`)).toHaveCount(0, LIVE);
    await expectAccessible(page, 'the changes list');
  } finally {
    await trash(page, id);
  }
});
