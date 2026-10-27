import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

/**
 * WP-026 end to end (REQ-INC-014 AC1–AC4): an admin adds a pick-list field; it reaches a
 * technician's open form live; the admin puts it on a template as required; the technician
 * fills it in, sees it on the record and filters the list by it; the admin asks for an index;
 * removing the field asks first and the record keeps its history.
 *
 * Suite-owned data only: the field, the template and the incident are named "E2E …"; the
 * incident goes to the trash here and global-teardown hard-deletes them (tooling/e2e_fixtures.py).
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

test('a custom pick list: added live, required by a template, filled, filtered, removed with history', async ({
  browser,
}) => {
  test.setTimeout(240_000);
  const tag = stamp();
  const label = `E2E Floor ${tag}`;
  const key = `e2e_floor_${tag}`;
  const templateName = `E2E Floors ${tag}`;
  const tech = await open(browser, 'tech', '/incidents/new');
  const admin = await open(browser, 'admin', '/admin/incidents/custom-fields');
  try {
    await expect(tech.page.getByTestId('inc-template')).toContainText('Standard incident');

    // Admin › Incidents › Custom fields: a pick list with two choices, named in two languages.
    await admin.page.getByTestId('cf-new').click();
    await pick(admin.page, 'cf-type', 'Pick one');
    await admin.page.getByTestId('cf-label-en').fill(label);
    await admin.page.getByTestId('cf-label-ar').fill(`الطابق ${tag}`);
    for (const choice of ['Ground', 'First']) {
      await admin.page.getByTestId('cf-choice-add').click();
      await admin.page.getByTestId('cf-choice-name-en').fill(choice);
      await admin.page.getByTestId('cf-choice-dialog').getByRole('button', { name: 'Add' }).click();
    }
    await admin.page.getByTestId('cf-save').click();
    await expect(admin.page.getByTestId(`cf-name-${key}`)).toHaveText(label);
    await expectAccessible(admin.page, 'custom fields');

    // Live on the technician's open form, by its label (never its key: AC3).
    await expect(tech.page.getByTestId(`inc-custom-${key}`)).toBeVisible(LIVE);
    await expect(tech.page.locator('main')).not.toContainText(key);

    // A template that requires it.
    await admin.page.getByRole('tab', { name: 'Templates', exact: true }).click();
    await admin.page.getByTestId('tpl-admin-new').click();
    await admin.page.getByTestId('tpl-editor-name-en').fill(templateName);
    await admin.page.getByTestId(`tpl-rule-custom.${key}-required`).click();
    await admin.page.getByTestId('tpl-editor-save').click();
    await expect(admin.page.getByText(templateName)).toBeVisible();

    // The technician uses it: required until filled.
    const form = tech.page;
    const subject = `E2E Floor call ${tag}`;
    await expect(async () => {
      await pick(form, 'inc-template', templateName);
    }).toPass(LIVE);
    await form.getByTestId('inc-subject').fill(subject);
    await pick(form, 'inc-requester', /^Adel E2E Admin$/);
    await form.getByTestId('inc-save').click();
    await expect(form.getByTestId(`error-custom-${key}`)).toHaveText('This field is required.');
    await pick(form, `inc-custom-${key}`, 'First');
    await form.getByTestId('inc-save').click();
    await form.getByRole('button', { name: 'Hand over and keep following' }).click();
    await expect(form.getByTestId('inc-heading')).toHaveText(subject);
    const id = form.url().split('/').at(-1) ?? '';
    created.push(id);
    await form.getByRole('tab', { name: 'Details' }).click();
    await expect(form.getByTestId(`inc-prop-custom.${key}`)).toHaveText('First');

    // Edit in place.
    await form.getByTestId(`inc-edit-custom.${key}`).click();
    await pick(form, `inc-input-custom.${key}`, 'Ground');
    await form.getByTestId(`inc-save-custom.${key}`).click();
    await expect(form.getByTestId(`inc-prop-custom.${key}`)).toHaveText('Ground');

    // AC1: the list filters on it.
    await admin.page.goto('/incidents');
    await pick(admin.page, 'inc-filter-custom-field', label);
    await pick(admin.page, 'inc-filter-custom-value', 'Ground');
    await expect(admin.page.getByTestId('inc-table')).toContainText(subject);
    await pick(admin.page, 'inc-filter-custom-value', 'First');
    await expect(admin.page.getByTestId('inc-table')).not.toContainText(subject);

    // AC2: an index on request; its state shows on the field.
    await admin.page.goto('/admin/incidents/custom-fields');
    await admin.page.getByTestId(`cf-edit-${key}`).click();
    await admin.page.getByText('For integrations and performance').click();
    await expect(admin.page.getByTestId('cf-api-name')).toContainText(`custom.${key}`);
    await admin.page.getByTestId('cf-request-index').click();
    // The index worker picks it up within a minute or so (D-088): pending, building, indexed.
    await expect(admin.page.getByTestId(`cf-index-${key}`)).toHaveText(
      /Index pending|Building index|Indexed/,
    );
    await expect(admin.page.getByTestId(`cf-index-${key}`)).toHaveText('Indexed', {
      timeout: 120_000,
    });

    // AC4: removing it asks first, with Retire recommended; removing anyway keeps the history.
    await admin.page.keyboard.press('Escape');
    await admin.page.getByTestId(`cf-remove-${key}`).click();
    await expect(admin.page.getByTestId('cf-remove-dialog')).toContainText(
      'Retiring it is recommended',
    );
    await admin.page.getByTestId('cf-remove-ok').click();
    await expect(admin.page.getByTestId(`cf-name-${key}`)).toHaveCount(0);
    await expect(form.getByTestId(`inc-prop-custom.${key}`)).toHaveCount(0, LIVE);
    await form.getByRole('tab', { name: /History/ }).click();
    await expect(form.getByTestId('inc-history')).toContainText(label);
    await expect(form.getByTestId('inc-history')).toContainText('Ground');
  } finally {
    await tech.context.close();
    await admin.context.close();
  }
});
