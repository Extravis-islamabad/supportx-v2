import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-020 incidents end to end in real browsers (parity file 01): a new incident with rich text
 * appears live in a second browser; an edit reaches the open record without a reload; a status
 * change asks for its reason; a technician handing an incident out of their reach is warned
 * first (D-053) and then cannot open it (D-052); the list says what its view leaves out
 * (Area 15); every screen is labelled and accessible in light, dark, high contrast and Arabic.
 *
 * Suite-owned data only: incidents, groups and sites are named "E2E …". Incidents go to the
 * trash at the end; global-teardown hard-deletes them with their history, and the groups and
 * sites (tooling/e2e_fixtures.py). The technician's default (group) scope is the product's.
 */

const LIVE = { timeout: 8_000 };
const stamp = () => String(Date.now()).slice(-7);

interface Me {
  csrf_token: string;
  user: { id: string; display_name: string };
}

interface Incident {
  id: string;
  display_id: string;
  version: number;
}

async function open(browser: Browser, user: 'tech' | 'admin', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

/** The API as the page's signed-in user (same session cookie, CSRF header, If-Match). */
async function call(
  page: Page,
  method: string,
  path: string,
  { body, version }: { body?: unknown; version?: number } = {},
) {
  const headers: Record<string, string> = { 'X-CSRF-Token': (await me(page)).csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function unit(page: Page, kind: 'groups' | 'sites', name: string, members: string[]) {
  const created = await call(page, 'POST', `/organization/${kind}`, { body: { name } });
  expect(created.status(), await created.text()).toBe(201);
  const id = ((await created.json()) as { id: string }).id;
  for (const member of members) {
    const added = await call(page, 'PUT', `/organization/${kind}/${id}/members/${member}`);
    expect([200, 204]).toContain(added.status());
  }
  return id;
}

async function createIncident(page: Page, body: Record<string, unknown>): Promise<Incident> {
  const response = await call(page, 'POST', '/incidents', { body });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as Incident;
}

async function trash(page: Page, ids: string[]): Promise<void> {
  for (const id of ids) {
    const found = await call(page, 'GET', `/incidents/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as Incident;
    await call(page, 'DELETE', `/incidents/${id}`, { version });
  }
}

/**
 * Open an Ant Design Select and wait until its list has finished opening: an option clicked
 * mid-animation can scroll the virtual list until the option is never rendered again.
 */
async function openSelect(page: Page, testId: string) {
  await page.getByTestId(testId).click();
  // The list just closed may still be leaving.
  const dropdown = page.locator('.ant-select-dropdown:visible:not([class*="-leave"])');
  await expect(dropdown).not.toHaveClass(/ant-slide-up-(appear|enter)/);
  return dropdown;
}

/** Pick an option in an Ant Design Select (searchable) by typing and clicking its text. */
async function pick(page: Page, testId: string, search: string, option: string | RegExp) {
  const select = page.getByTestId(testId);
  await openSelect(page, testId);
  const input = select.locator('input');
  if ((await input.count()) > 0 && (await input.isEditable())) await input.fill(search);
  await page
    .locator('.ant-select-dropdown:visible, .ant-select-tree-list:visible')
    .getByText(option)
    .first()
    .click();
}

let techId = '';
let adminId = '';
let desk = '';
let network = '';
let site = '';
const created: string[] = [];

test.beforeAll(async ({ browser }) => {
  const tech = await open(browser, 'tech', '/');
  techId = (await me(tech.page)).user.id;
  await tech.context.close();
  const admin = await open(browser, 'admin', '/');
  adminId = (await me(admin.page)).user.id;
  const tag = stamp();
  // The technician is in E2E Desk and E2E Site, not in E2E Network (D-052 group scope).
  desk = await unit(admin.page, 'groups', `E2E Desk ${tag}`, [techId]);
  network = await unit(admin.page, 'groups', `E2E Network ${tag}`, []);
  site = await unit(admin.page, 'sites', `E2E Site ${tag}`, [techId, adminId]);
  await admin.context.close();
});

test.afterAll(async ({ browser }) => {
  const admin = await open(browser, 'admin', '/');
  await trash(admin.page, created);
  await admin.context.close();
});

test('a new incident with rich text appears live for the technician; edits reach the open record; a status change asks for its reason', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const tech = await open(browser, 'tech', '/incidents');
  const admin = await open(browser, 'admin', '/incidents/new');
  const subject = `E2E Printer ${stamp()}`;
  try {
    // The technician's list is open before the incident exists.
    await (await openSelect(tech.page, 'inc-view')).getByText(/^My open/).click();

    // Logged through the form: requester, group, technician (with email as the second line),
    // impact and urgency with the priority shown live, a description in rich text.
    const form = admin.page;
    await form.getByTestId('inc-subject').fill(subject);
    await pick(form, 'inc-requester', 'E2E Admin', /^Adel E2E Admin$/);
    await pick(form, 'inc-site', 'E2E Site', /^E2E Site /);
    await pick(form, 'inc-group', 'E2E Desk', /^E2E Desk /);
    const option = (await openSelect(form, 'inc-technician')).getByText('e2e.tech@demo.test', {
      exact: false,
    });
    await expect(option).toBeVisible(); // two people of one name stay distinguishable (Area 15)
    await option.click();
    await pick(form, 'inc-impact', '', 'A team');
    await pick(form, 'inc-urgency', '', 'High – work stopped');
    await expect(form.getByTestId('inc-priority-preview')).toContainText('P3 – Medium');
    const editor = form.getByTestId('inc-description-editor');
    await editor.click();
    await form.keyboard.type('Paper stuck in ');
    await form.getByTestId('rt-bold').click();
    await form.keyboard.type('tray 2');
    await form.getByTestId('inc-save').click();
    await expect(form.getByTestId('inc-heading')).toHaveText(subject);
    const id = form.url().split('/').at(-1) ?? '';
    created.push(id);
    await expect(form.getByTestId('inc-status')).toHaveText('Assigned'); // REQ-INC-050
    // The record opens on Conversation (D-081); description and fields are on Details.
    await form.getByRole('tab', { name: 'Details' }).click();
    await expect(form.getByTestId('inc-description').locator('strong')).toHaveText('tray 2');

    // Live in the technician's "My open" list, no reload.
    await expect(tech.page.getByText(subject)).toBeVisible(LIVE);
    await tech.page.getByText(subject).click();
    await expect(tech.page.getByTestId('inc-heading')).toHaveText(subject);
    await tech.page.getByRole('tab', { name: 'Details' }).click();

    // The admin edits urgency in place; the technician's open record follows by itself.
    await form.getByTestId('inc-edit-urgency').click();
    await pick(form, 'inc-input-urgency', '', 'Critical – business stopped');
    await form.getByTestId('inc-save-urgency').click();
    await expect(tech.page.getByTestId('inc-priority').first()).toHaveAttribute(
      'data-priority',
      'p2',
      LIVE,
    );

    // A status that needs a reason asks for it; the reason shows on the record and in history.
    await tech.page.getByTestId('inc-action-wait_requester').click();
    await tech.page.getByTestId('inc-reason-confirm').click();
    await expect(tech.page.getByTestId('inc-reason-code-error')).toHaveText('Choose a reason.');
    await pick(tech.page, 'inc-reason-code', '', 'Needs more information');
    await tech.page.getByTestId('inc-reason-text').fill('Which printer exactly?');
    await tech.page.getByTestId('inc-reason-confirm').click();
    await expect(tech.page.getByTestId('inc-status')).toHaveText('Waiting for requester');
    await expect(tech.page.getByTestId('inc-status-reason')).toContainText(
      'Needs more information',
    );
    await expect(admin.page.getByTestId('inc-status')).toHaveText('Waiting for requester', LIVE);
    await tech.page.getByRole('tab', { name: /History/ }).click();
    const history = tech.page.getByTestId('inc-history');
    await expect(history).toContainText('Which printer exactly?');
    await expect(history.getByTestId('inc-history-automatic').first()).toBeVisible();
    await tech.page.screenshot({ path: 'test-results/incident-history.png', fullPage: true });
  } finally {
    await tech.context.close();
    await admin.context.close();
  }
});

test('D-052/D-053/D-068: the technician sees the site queue, keeps following what they hand over, and loses it on unfollow', async ({
  browser,
}) => {
  test.setTimeout(120_000);
  const admin = await open(browser, 'admin', '/incidents');
  // Unassigned at the technician's site: in their queue (D-052 rule 3).
  const queued = await createIncident(admin.page, {
    subject: `E2E Queue ${stamp()}`,
    requester_id: adminId,
    site_id: site,
  });
  created.push(queued.id);
  await admin.context.close();
  const tech = await open(browser, 'tech', `/incidents/${queued.id}`);
  try {
    await expect(tech.page.getByTestId('inc-display-id')).toContainText(queued.display_id);
    // Take it into E2E Desk, then hand it to E2E Network (not one of the technician's groups).
    await tech.page.getByTestId('inc-op-take').click();
    await expect(tech.page.getByTestId('inc-status')).toHaveText('Assigned');
    await tech.page.getByTestId('inc-op-assign').click();
    await pick(tech.page, 'inc-assign-group', 'E2E Network', /^E2E Network /);
    await pick(tech.page, 'inc-assign-reason', '', 'Wrong group');
    await tech.page.getByTestId('inc-assign-confirm').click();
    const warning = tech.page.getByTestId('inc-handover-warning');
    // D-068 / REQ-INC-151: keep following is ticked by default and says what it means.
    await expect(tech.page.getByTestId('inc-handover-keep-following')).toBeChecked();
    await expect(warning).toContainText('You keep following it');
    await expectAccessible(tech.page, 'hand-over warning');
    await tech.page.getByTestId('inc-handover-confirm').click();
    // Still open for them: read-only, following, and listed as a follower with access.
    await expect(tech.page.getByTestId('inc-follow')).toContainText('Unfollow');
    await expect(tech.page.getByTestId('inc-op-assign')).toBeDisabled();
    await tech.page.getByRole('tab', { name: 'Details' }).click();
    await expect(tech.page.getByTestId('inc-followers')).toContainText(
      'Kept after handing it over',
    );
    // Unfollowing gives up the access the follow gave (AC4); then it is out of reach (AC3).
    await tech.page.getByTestId('inc-follow').click();
    // It asks first: unfollowing removes the access the follow gave (QA BUG-09).
    await tech.page.locator('.ant-popover').getByRole('button', { name: 'Unfollow' }).click();
    await expect(tech.page).toHaveURL(/\/incidents$/);
    await tech.page.goto(`/incidents/${queued.id}`);
    await expect(tech.page.getByTestId('inc-not-found')).toBeVisible();
  } finally {
    await tech.context.close();
  }
  expect(network).not.toBe('');
  expect(desk).not.toBe('');
});

test('incident screens are labelled and accessible in light, dark, high contrast and Arabic (RTL); the view says what it leaves out', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const admin = await open(browser, 'admin', '/incidents');
  const item = await createIncident(admin.page, {
    subject: `E2E Accessible ${stamp()}`,
    requester_id: adminId,
    group_id: desk,
    impact: 'organisation',
    urgency: 'critical',
    description: '<p>Line <strong>one</strong></p><p dir="auto">السطر الثاني</p>',
  });
  created.push(item.id);
  const resolved = await createIncident(admin.page, {
    subject: `E2E Resolved ${stamp()}`,
    requester_id: adminId,
  });
  created.push(resolved.id);
  // Resolving needs a resolution by default (WP-020f, D1).
  const act = await call(admin.page, 'POST', `/incidents/${resolved.id}/actions/resolve`, {
    version: resolved.version,
    body: { resolution: '<p>Fixed</p>' },
  });
  expect(act.status()).toBe(200);
  const page = admin.page;
  try {
    await page.reload();
    const notice = page.getByTestId('inc-view-notice');
    await expect(notice).toContainText('View “All open”');
    await expect(notice).toContainText('not in this view'); // the resolved one is outside it
    await page.getByTestId('inc-show-all').click();
    await expect(page.getByTestId(`inc-row-${resolved.display_id}`)).toBeVisible();

    const pages = [
      ['list', '/incidents'],
      ['record', `/incidents/${item.id}`],
      ['form', '/incidents/new'],
    ] as const;
    for (const theme of ['light', 'dark', 'high_contrast'] as const) {
      await page.evaluate((value) => {
        window.localStorage.setItem('supportx.theme_mode', value);
      }, theme);
      for (const [name, path] of pages) {
        await page.goto(path);
        await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
        if (name === 'record') await expect(page.getByTestId('inc-heading')).toBeVisible();
        if (name === 'form') await expect(page.getByTestId('inc-description-editor')).toBeVisible();
        if (name === 'list') await expect(page.getByTestId('inc-table')).toBeVisible();
        await expectAccessible(page, `incident ${name} (${theme})`);
      }
    }
    await page.evaluate(() => {
      window.localStorage.setItem('supportx.theme_mode', 'light');
    });
    await page.goto(`/incidents/${item.id}`);
    await page.getByTestId('appearance-menu').click();
    await page.getByTestId('language-select').click();
    await page.locator('.ant-select-item-option[title="العربية"]').click();
    await page.getByTestId('appearance-menu').click();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('inc-status')).toHaveText('جديدة');
    await expect(page.getByTestId('inc-priority').first()).toContainText('P1 – حرجة');
    const text = (await page.locator('main, #main').first().textContent()) ?? '';
    expect(text).not.toMatch(
      /not_from_status|no_permission|work_item_|\bnew\b|\bp1\b|organisation/,
    );
    await expectAccessible(page, 'incident record (Arabic, RTL)');
    // The language is stored with the user (QA BUG-04): a full page load keeps it.
    await page.goto('/incidents');
    await expect(page.getByTestId('inc-table')).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expectAccessible(page, 'incident list (Arabic, RTL)');
    await page.goto('/incidents/new');
    await expect(page.getByTestId('inc-description-editor')).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expectAccessible(page, 'incident form (Arabic, RTL)');
    await page.screenshot({ path: 'test-results/incident-form-ar.png', fullPage: true });
  } finally {
    // Back to the identity provider's language for the suite user (a stored preference).
    await resetLanguage(page);
    await admin.context.close();
  }
});
