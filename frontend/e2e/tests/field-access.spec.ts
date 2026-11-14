import { expect, test, type Browser, type Page } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

// ADR-047 slice c: an administrator hides a field for a role on the role editor's Field access
// tab, and a technician's open record says "Not shown to you" at once, with no refresh (rule c).
// The rule is on the built-in technician role, so it is removed again however the test ends.

const LIVE = { timeout: 5_000 };
const FIELD = 'impact_details';

interface Me {
  csrf_token: string;
  user: { id: string };
}
interface Rule {
  id: string;
  field: string;
  record_type: string;
  version: number;
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

async function call(page: Page, method: string, path: string, body?: unknown, version?: number) {
  const headers: Record<string, string> = { 'X-CSRF-Token': (await me(page)).csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  return page.request.fetch(`/api/v1${path}`, { method, data: body, headers });
}

async function open(browser: Browser, user: 'tech' | 'admin', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

/** Takes away the technician role's impact-details rule, if one is left (suite-owned). */
async function removeRule(admin: Page, roleId: string): Promise<void> {
  const listed = await call(admin, 'GET', `/field-access/rules?role_id=${roleId}`);
  for (const rule of (await listed.json()) as Rule[]) {
    if (rule.field === FIELD && rule.record_type === 'incident') {
      await call(admin, 'DELETE', `/field-access/rules/${rule.id}`, undefined, rule.version);
    }
  }
}

test('a field hidden for a role reads "Not shown to you" on an open record, live', async ({
  browser,
}) => {
  const admin = await open(browser, 'admin', '/admin/roles');
  const tech = await open(browser, 'tech', '/');
  const roles = (await (await call(admin.page, 'GET', '/roles')).json()) as {
    id: string;
    key: string;
  }[];
  const technician = roles.find((r) => r.key === 'technician');
  if (technician === undefined) throw new Error('no technician role');
  await removeRule(admin.page, technician.id); // a leftover of an interrupted run
  try {
    const techId = (await me(tech.page)).user.id;
    const made = await call(admin.page, 'POST', '/incidents', {
      subject: `E2E field access ${String(Date.now())}`,
      requester_id: (await me(admin.page)).user.id,
      technician_id: techId,
      impact_details: 'Payroll stops for the whole site',
    });
    expect(made.status(), await made.text()).toBe(201);
    const incident = (await made.json()) as { id: string };

    await tech.page.goto(`/incidents/${incident.id}`);
    const properties = tech.page.getByTestId('inc-properties');
    await expect(properties).toContainText('Payroll stops');

    // The administrator hides the field for technicians: one row, saved at once.
    await admin.page.getByTestId('role-row-technician').click();
    await admin.page.getByRole('tab', { name: 'Field access' }).click();
    await expect(admin.page.getByTestId('field-access-help')).toBeVisible();
    await admin.page.getByTestId(`field-access-mode-${FIELD}`).click();
    await admin.page.locator('.ant-select-item-option[title="Hidden"]').last().click();
    await expect(admin.page.getByText('Field access saved')).toBeVisible();
    await expectAccessible(admin.page, 'role field access tab');
    await admin.page.screenshot({ path: 'test-results/field-access-tab.png', fullPage: true });

    // The technician's open record changes with no reload: the value is gone, the row says why.
    await expect(properties.getByTestId('restricted-hidden')).toHaveText('Not shown to you', LIVE);
    await expect(properties).not.toContainText('Payroll stops');
    await expectAccessible(tech.page, 'record with a hidden field');
    await tech.page.screenshot({ path: 'test-results/field-access-record.png', fullPage: true });

    // Who sees it: in a modal, never a drawer over the drawer.
    await admin.page.getByTestId(`field-access-who-${FIELD}`).click();
    const dialog = admin.page.locator('.ant-modal').filter({ hasText: 'Who sees' });
    await expect(dialog.getByTestId('field-access-effective-hidden')).toBeVisible();
    await expectAccessible(admin.page, 'who sees a field');
  } finally {
    await removeRule(admin.page, technician.id);
    await admin.context.close();
    await tech.context.close();
  }
});
