import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

/**
 * WP-029 end to end: an admin's business rule changes a technician's new incident in the same
 * save and the history says why; a trigger acts after the move to Resolved and the record's
 * Automation tab shows each action's outcome; two triggers that set each other off are stopped
 * at the limit, the record warns naming both and the admins' banner appears; a status change
 * limited to admins is shown disabled with the reason; the screens pass axe.
 *
 * Suite-owned data only: everything is named "E2E …" with a stamp and matches only incidents
 * whose subject carries that stamp, so other incidents are never touched. Rules and triggers
 * are removed and transition settings reset afterwards; incidents go to the trash.
 * Needs the consumers worker (triggers run after the commit).
 */

const LIVE = { timeout: 15_000 };
const stamp = () => String(Date.now()).slice(-7);

async function open(browser: Browser, user: 'tech' | 'admin', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as { csrf_token: string };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

/** Like `pick`, typing first: long lists render only what is in view (virtual lists). */
async function search(page: Page, testId: string, option: string) {
  await page.getByTestId(testId).click();
  await page.getByTestId(testId).locator('input').fill(option);
  const list = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').last();
  await list
    .locator('.ant-select-item-option-content', { hasText: new RegExp(`^${option}$`) })
    .first()
    .click();
  await expect(list).toBeHidden();
}

async function pick(page: Page, testId: string, option: string | RegExp) {
  await page.getByTestId(testId).click();
  const text = typeof option === 'string' ? new RegExp(`^${option}$`) : option;
  const list = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').last();
  await list.locator('.ant-select-item-option-content', { hasText: text }).first().click();
  await expect(list).toBeHidden();
}

const made = { rules: [] as string[], triggers: [] as string[], incidents: [] as string[] };
// The shared e2e technician joins a group of this journey: leave it afterwards, or later
// journeys see them in two groups (Take then asks which, incidents.spec D-052).
const memberships: { group: string; user: string }[] = [];
let closeLimited = false;

test.afterAll(async ({ browser }) => {
  const admin = await open(browser, 'admin', '/');
  const remove = async (path: string) => {
    const found = await call(admin.page, 'GET', path);
    if (found.status() !== 200) return;
    const { version } = (await found.json()) as { version: number };
    await call(admin.page, 'DELETE', path, undefined, version);
  };
  const listed = async (kind: 'rules' | 'triggers') =>
    (await (await call(admin.page, 'GET', `/automation/${kind}?record_type=incident`)).json()) as {
      id: string;
      version: number;
    }[];
  for (const kind of ['rules', 'triggers'] as const) {
    for (const row of (await listed(kind)).filter((r) => made[kind].includes(r.id))) {
      await call(admin.page, 'DELETE', `/automation/${kind}/${row.id}`, undefined, row.version);
    }
  }
  if (closeLimited) {
    await call(
      admin.page,
      'DELETE',
      '/automation/transitions/close?record_type=incident',
      undefined,
      1,
    );
  }
  for (const id of made.incidents) await remove(`/incidents/${id}`);
  for (const { group, user } of memberships) {
    await call(admin.page, 'DELETE', `/organization/groups/${group}/members/${user}`);
  }
  await admin.context.close();
});

test('rules, triggers, the loop guard and who may run a move, from admin screens to the record', async ({
  browser,
}) => {
  test.setTimeout(300_000);
  const tag = stamp();
  const subject = `E2E automation ${tag}`;
  const admin = await open(browser, 'admin', '/admin/automation/business-rules');
  const tech = await open(browser, 'tech', '/incidents/new');
  try {
    // 1. A business rule built on the screen: subject contains the stamp → priority P1.
    await admin.page.getByTestId('rule-add').click();
    await admin.page.getByTestId('rule-name').fill(`E2E rule ${tag}`);
    await admin.page.getByTestId('condition-add').click();
    await search(admin.page, 'condition-0-field', 'Subject');
    await pick(admin.page, 'condition-0-op', 'contains');
    await admin.page.getByTestId('condition-0-value').fill(tag);
    await search(admin.page, 'action-0-field', 'Priority');
    await pick(admin.page, 'action-0-value', /^P1/);
    await pick(admin.page, 'action-0-mode', 'Replace what was entered');
    await pick(admin.page, 'rule-state', 'On');
    await expectAccessible(admin.page, 'business rule editor');
    await admin.page.getByTestId('rule-save').click();
    const row = admin.page.getByTestId(`rule-row-E2E rule ${tag}`);
    await expect(row).toBeVisible();
    const rules = (await (
      await call(admin.page, 'GET', '/automation/rules?record_type=incident')
    ).json()) as { id: string; name: string }[];
    made.rules.push(...rules.filter((r) => r.name === `E2E rule ${tag}`).map((r) => r.id));

    // 2. Triggers (API, the editor is covered by unit tests): resolved → a note; a ping-pong pair.
    const contains = { field: 'subject', op: 'contains', value: tag };
    for (const body of [
      {
        name: `E2E resolved ${tag}`,
        events: ['status_changed'],
        conditions: {
          and: [contains, { field: 'status', op: 'changed_to', value: 'resolved' }],
        },
        actions: [{ kind: 'note', text: 'Check the fix with the user.' }],
      },
      {
        name: `E2E ping ${tag}`,
        events: ['updated'],
        conditions: { and: [contains, { field: 'tags', op: 'changed_to', value: ['ping'] }] },
        actions: [{ kind: 'set', field: 'tags', value: ['pong'], mode: 'overwrite' }],
      },
      {
        name: `E2E pong ${tag}`,
        events: ['updated'],
        conditions: { and: [contains, { field: 'tags', op: 'changed_to', value: ['pong'] }] },
        actions: [{ kind: 'set', field: 'tags', value: ['ping'], mode: 'overwrite' }],
      },
    ]) {
      const created = await call(admin.page, 'POST', '/automation/triggers', {
        record_type: 'incident',
        state: 'enabled',
        ...body,
      });
      expect(created.status()).toBe(201);
      made.triggers.push(((await created.json()) as { id: string }).id);
    }

    // 3. The technician's new incident, in a group of theirs (group scope, D-052): P1 by the
    // rule, and the history says which rule.
    const techId = (
      (await (await tech.page.request.get('/api/v1/auth/me')).json()) as {
        user: { id: string };
      }
    ).user.id;
    const groupName = `E2E Automation ${tag}`;
    const group = await call(admin.page, 'POST', '/organization/groups', { name: groupName });
    expect(group.status()).toBe(201);
    const groupId = ((await group.json()) as { id: string }).id;
    expect([200, 204]).toContain(
      (await call(admin.page, 'PUT', `/organization/groups/${groupId}/members/${techId}`)).status(),
    );
    memberships.push({ group: groupId, user: techId });
    await tech.page.reload();
    await tech.page.getByTestId('inc-subject').fill(subject);
    const requester = tech.page.getByTestId('inc-requester');
    await requester.click();
    await requester.locator('input').fill('E2E Admin');
    await tech.page
      .locator('.ant-select-dropdown:visible')
      .getByText(/^Adel E2E Admin$/)
      .first()
      .click();
    const groupPicker = tech.page.getByTestId('inc-group');
    await groupPicker.click();
    await groupPicker.locator('input').fill(groupName);
    await tech.page.locator('.ant-select-dropdown:visible').getByText(groupName).first().click();
    await tech.page.getByTestId('inc-save').click();
    await expect(tech.page).toHaveURL(/\/incidents\/[0-9a-f-]{36}$/, LIVE);
    const id = tech.page.url().split('/').pop() ?? '';
    made.incidents.push(id);
    await expect(tech.page.getByTestId('inc-priority').first()).toContainText('P1', LIVE);
    await tech.page.getByRole('tab', { name: /History/ }).click();
    await expect(
      tech.page.getByTestId('inc-history-why').filter({ hasText: `E2E rule ${tag}` }),
    ).toBeVisible(LIVE);

    // 4. Resolve: the trigger adds its note after the commit, shown with its outcome.
    await tech.page.getByTestId('inc-action-resolve').click();
    // Resolving asks for the resolution (WP-020f, REQ-INC-090).
    await tech.page.getByTestId('inc-resolution-editor').click();
    await tech.page.keyboard.type('Restarted the service');
    await tech.page.getByTestId('inc-reason-confirm').click();
    await tech.page.getByRole('tab', { name: 'Automation' }).click();
    await expect(tech.page.getByTestId('inc-automation')).toContainText(
      `E2E resolved ${tag}`,
      LIVE,
    );
    await expect(tech.page.getByTestId('inc-automation-action-0')).toContainText('Done');
    await expectAccessible(tech.page, 'automation panel');

    // 5. Ping-pong: the guard stops it, the record warns naming both, the admin is told.
    await tech.page.getByTestId('inc-action-reopen').click();
    const record = (await (await call(tech.page, 'GET', `/incidents/${id}`)).json()) as {
      version: number;
    };
    expect(
      (
        await call(tech.page, 'PATCH', `/incidents/${id}`, { tags: ['ping'] }, record.version)
      ).status(),
    ).toBe(200);
    const warning = tech.page.getByTestId('inc-loop-warning');
    await expect(warning).toContainText(`E2E ping ${tag}`, { timeout: 30_000 });
    await expect(warning).toContainText(`E2E pong ${tag}`);
    await expect(admin.page.getByTestId('loop-banner')).toBeVisible(LIVE);

    // 6. "Close" limited to admins: the technician sees it disabled with the reason.
    const saved = await call(
      admin.page,
      'PUT',
      '/automation/transitions/close?record_type=incident',
      { roles: ['tenant_admin'] },
      0,
    );
    expect(saved.status()).toBe(200);
    closeLimited = true;
    await tech.page.reload();
    await expect(tech.page.getByTestId('inc-action-close-reason')).toHaveAttribute(
      'data-reason',
      /not_for_you|not_from_status/,
    );

    // 7. The admin screens, in Arabic too.
    for (const section of ['triggers', 'transitions', 'routing']) {
      await admin.page.goto(`/admin/automation/${section}`);
      await expectAccessible(admin.page, `admin ${section}`);
    }
  } finally {
    await tech.context.close();
    await admin.context.close();
  }
});
