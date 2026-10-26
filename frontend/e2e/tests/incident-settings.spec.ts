import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-020c end to end: an admin's settings change reaches a technician's open form live (a new
 * level appears in the picker, no reload); an admin builds a template in the UI that a
 * technician then uses (required field, hidden field said out loud, starting values); the
 * template is named on the record; switching templates asks before clearing; the settings
 * screens are accessible in light, dark and Arabic (RTL).
 *
 * Suite-owned data only: the template, the level value and the incident are named "E2E …";
 * the incident goes to the trash here and global-teardown hard-deletes all three
 * (tooling/e2e_fixtures.py). Nothing the tenant had is changed.
 */

const LIVE = { timeout: 8_000 };
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

async function pick(page: Page, testId: string, option: string | RegExp) {
  await page.getByTestId(testId).click();
  await page.locator('.ant-select-dropdown:visible').getByText(option).first().click();
}

const created: string[] = [];

test.afterAll(async ({ browser }) => {
  const admin = await open(browser, 'admin', '/');
  for (const id of created) {
    const found = await call(admin.page, 'GET', `/incidents/${id}`);
    if (found.status() !== 200) continue;
    const { version } = (await found.json()) as { version: number };
    await call(admin.page, 'DELETE', `/incidents/${id}`, undefined, version);
  }
  await admin.context.close();
});

test('a new level reaches an open form live; a template built by an admin is used by a technician', async ({
  browser,
}) => {
  test.setTimeout(180_000);
  const tag = stamp();
  const level = `E2E Vendor ${tag}`;
  const templateName = `E2E Outage ${tag}`;
  const tech = await open(browser, 'tech', '/incidents/new');
  const admin = await open(browser, 'admin', '/admin/incidents/levels');
  try {
    // The technician's form is open before the admin adds the level.
    await expect(tech.page.getByTestId('inc-template')).toContainText('Standard incident');

    // Admin › Incidents › Levels: add a value in two languages.
    await admin.page.getByTestId('list-level-add').click();
    await admin.page.getByTestId('list-level-dialog-name-en').fill(level);
    await admin.page.getByTestId('list-level-dialog-name-ar').fill(`مورد ${tag}`);
    await admin.page.getByRole('button', { name: 'Save' }).click();
    await expect(admin.page.getByText(level)).toBeVisible();

    // Live on the technician's open form (no reload).
    await expect(async () => {
      await tech.page.getByTestId('inc-level').click();
      await expect(tech.page.locator('.ant-select-dropdown:visible').getByText(level)).toBeVisible({
        timeout: 1_000,
      });
    }).toPass(LIVE);
    await tech.page.keyboard.press('Escape');

    // Admin › Incidents › Templates: a template that requires impact details, hides tags and
    // starts with urgency "High".
    await admin.page.getByRole('tab', { name: 'Templates', exact: true }).click();
    await admin.page.getByTestId('tpl-admin-new').click();
    await admin.page.getByTestId('tpl-editor-name-en').fill(templateName);
    await admin.page.getByTestId('tpl-editor-group').fill('E2E Infrastructure');
    await admin.page.getByTestId('tpl-rule-impact_details-required').click();
    await admin.page.getByTestId('tpl-rule-tags-shown').click();
    await pick(admin.page, 'tpl-default-urgency', 'High – work stopped');
    await admin.page.getByTestId('tpl-editor-save').click();
    await expect(admin.page.getByText(templateName)).toBeVisible();
    await expectAccessible(admin.page, 'incident templates');

    // The technician switches to it: typed text stays; tags are said to be hidden; urgency
    // takes the template's starting value; impact details are required.
    const form = tech.page;
    const subject = `E2E Outage call ${tag}`;
    await form.getByTestId('inc-subject').fill(subject);
    await expect(async () => {
      await pick(form, 'inc-template', templateName);
    }).toPass(LIVE);
    await expect(form.getByTestId('inc-hidden-fields')).toContainText('Tags');
    await expect(form.getByTestId('inc-urgency')).toContainText('High');
    await expect(form.getByTestId('inc-subject')).toHaveValue(subject);
    await pick(form, 'inc-requester', /^Adel E2E Admin$/);
    await form.getByTestId('inc-save').click();
    await expect(form.getByTestId('error-impact_details')).toHaveText('This field is required.');
    await form.getByTestId('inc-impact-details').fill('Second floor, about 40 people');
    await pick(form, 'inc-level', level);
    await form.getByTestId('inc-save').click();
    // The technician is in no group here: logging it hands it out of their reach (D-053);
    // keeping it followed keeps it open to them (D-068).
    await form.getByRole('button', { name: 'Hand over and keep following' }).click();
    await expect(form.getByTestId('inc-heading')).toHaveText(subject);
    created.push(form.url().split('/').at(-1) ?? '');
    await form.getByRole('tab', { name: 'Details' }).click();
    await expect(form.getByTestId('inc-prop-template_id')).toContainText(templateName);
    await expect(form.getByTestId('inc-prop-level')).toContainText(level);
    await expect(form.getByTestId('inc-prop-impact_details')).toContainText('Second floor');

    // Retire the level: the record keeps showing it, live.
    await admin.page.getByRole('tab', { name: 'Levels', exact: true }).click();
    const row = admin.page.getByRole('row', { name: new RegExp(level) });
    await row.getByRole('button', { name: 'Retire' }).click();
    await admin.page.getByRole('button', { name: 'Retire' }).last().click();
    await expect(row.getByText('Retired')).toBeVisible();
    await expect(form.getByTestId('inc-prop-level')).toContainText(level);

    // Turn the template off: it leaves new forms but still names the record.
    await admin.page.getByRole('tab', { name: 'Templates', exact: true }).click();
    const tplRow = admin.page.getByRole('row', { name: new RegExp(templateName) });
    await tplRow.getByRole('button', { name: 'Turn off' }).click();
    await admin.page.getByRole('button', { name: 'Turn off' }).last().click();
    await expect(tplRow.getByText('Off')).toBeVisible();
    await form.reload();
    await form.getByRole('tab', { name: 'Details' }).click();
    await expect(form.getByTestId('inc-prop-template_id')).toContainText(templateName);
  } finally {
    await tech.context.close();
    await admin.context.close();
  }
});

test('switching templates asks before clearing what was typed', async ({ browser }) => {
  const tag = stamp();
  const admin = await open(browser, 'admin', '/incidents/new');
  const name = `E2E Quick ${tag}`;
  try {
    const made = await call(admin.page, 'POST', '/incidents/templates', {
      labels: { en: name },
      fields: { impact_details: { shown: false } },
    });
    expect(made.status(), await made.text()).toBe(201);
    const form = admin.page;
    await form.getByTestId('inc-impact-details').fill('Whole building');
    await expect(async () => {
      await pick(form, 'inc-template', name);
    }).toPass(LIVE);
    const dialog = form.getByTestId('inc-template-switch');
    await expect(dialog).toContainText('Impact details');
    await dialog.getByRole('button', { name: 'Keep this template' }).click();
    await expect(form.getByTestId('inc-impact-details')).toHaveValue('Whole building');
    await pick(form, 'inc-template', name);
    await form
      .getByTestId('inc-template-switch')
      .getByRole('button', {
        name: 'Switch and clear them',
      })
      .click();
    await expect(form.getByTestId('inc-impact-details')).toHaveCount(0);
    await expect(form.getByTestId('inc-hidden-fields')).toContainText('Impact details');
    const { id, version } = (await made.json()) as { id: string; version: number };
    await call(admin.page, 'PATCH', `/incidents/templates/${id}`, { disabled: true }, version);
  } finally {
    await admin.context.close();
  }
});

test('the settings screens are accessible in light, dark and Arabic (RTL)', async ({ browser }) => {
  test.setTimeout(150_000);
  const admin = await open(browser, 'admin', '/admin/incidents/general');
  const page = admin.page;
  try {
    for (const section of ['general', 'statuses', 'priority', 'categories', 'templates']) {
      await page.goto(`/admin/incidents/${section}`);
      await expect(page.getByTestId('settings-sections')).toBeVisible();
      await expectAccessible(page, `incident settings ${section}`);
    }
    // Dark, through its stored preference (the picker itself is covered by shell.spec.ts).
    await page.evaluate(() => {
      window.localStorage.setItem('supportx.theme_mode', 'dark');
    });
    await page.goto('/admin/incidents/priority');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByTestId('settings-matrix')).toBeVisible();
    await expectAccessible(page, 'incident settings (dark)');
    // Arabic: stored with the user, put back by resetLanguage at the end.
    const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
      user: { id: string };
    };
    const user = (await (await page.request.get(`/api/v1/users/${me.user.id}`)).json()) as {
      version: number;
    };
    const arabic = await call(
      page,
      'PATCH',
      `/users/${me.user.id}`,
      { ui_locale: 'ar' },
      user.version,
    );
    expect(arabic.status(), await arabic.text()).toBe(200);
    await page.goto('/admin/incidents/templates');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByTestId('settings-templates')).toBeVisible();
    await expectAccessible(page, 'incident settings (Arabic)');
    await page.goto('/incidents/new');
    await expect(page.getByTestId('inc-form')).toBeVisible();
    await expectAccessible(page, 'new incident form (Arabic)');
    await page.screenshot({ path: 'test-results/incident-form-ar.png', fullPage: true });
  } finally {
    await page.evaluate(() => {
      window.localStorage.removeItem('supportx.theme_mode');
    });
    await resetLanguage(page);
    await admin.context.close();
  }
});
