import { expect, test, type APIResponse, type Browser, type Page } from '@playwright/test';

import { expectAccessible, signInAs } from './helpers';

// ADR-047 slice c: an administrator hides a field for a role on the role editor's Field access
// tab, and a technician's open record says "Not shown to you" at once, with no refresh (rule c).
// The rule is on the built-in technician role, so it is removed again however the test ends.

// Live: the refetch after an access change waits up to 3 s at random (RealtimeProvider).
const LIVE = { timeout: 8_000 };
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

interface Session {
  tenant?: { id?: string };
  user: { id: string; roles?: string[] };
}

/**
 * The nightly k3d run's open question (a hidden field still served about 2 s after its rule):
 * logs who and where each side is, and polls the technician's read for up to 10 s. IDs, role
 * keys and booleans only, never a field's value. Never fails the test itself.
 */
async function logDiagnostics(
  admin: Page,
  tech: Page,
  incidentId: string,
  technicianRoleId: string,
  ruleRoleId: string | undefined,
): Promise<void> {
  // Never fails the spec: a non-JSON answer (a 502) or a thrown request is logged and skipped.
  const json = async (response: APIResponse): Promise<unknown> => {
    try {
      return await response.json();
    } catch {
      return null;
    }
  };
  try {
    const session = async (page: Page) =>
      ((await json(await page.request.get('/api/v1/auth/me'))) ?? { user: {} }) as Session;
    const [adminSession, techSession] = [await session(admin), await session(tech)];
    // Through the admin's session: the technician's direct roles and the roles their groups
    // carry. "Clearest wins": a second role without the rule (one an earlier spec gave a group
    // they're in) leaves the field visible, so these IDs tell that from a delay (lane B). The
    // user row (`/users/{id}`) carries no roles: `/users/{id}/access` does.
    const techUserRead = await admin.request.get(`/api/v1/users/${techSession.user.id}/access`);
    const techAccess = ((await json(techUserRead)) ?? {}) as {
      role_ids?: unknown;
      group_roles?: unknown;
    };
    const roleIds = Array.isArray(techAccess.role_ids) ? techAccess.role_ids.map(String) : null;
    const groupRoles = Array.isArray(techAccess.group_roles)
      ? techAccess.group_roles.map((g: unknown) => {
          const pair = (g ?? {}) as { role_id?: unknown; group_id?: unknown };
          return { role_id: String(pair.role_id), group_id: String(pair.group_id) };
        })
      : null;
    const polls: {
      ms: number;
      status: number;
      value: boolean | null;
      hidden: boolean | null;
      pod: string | null;
    }[] = [];
    const started = Date.now();
    while (Date.now() - started < 10_000) {
      const read = await tech.request.get(`/api/v1/incidents/${incidentId}`);
      const status = read.status(); // before the body: a 502 has none worth reading
      const body = (await json(read)) as {
        impact_details?: unknown;
        hidden_fields?: unknown;
      } | null;
      const hidden =
        body === null
          ? null
          : Array.isArray(body.hidden_fields) && body.hidden_fields.includes(FIELD);
      polls.push({
        ms: Date.now() - started,
        status,
        value:
          body === null
            ? null
            : typeof body.impact_details === 'string' && body.impact_details !== '',
        hidden,
        pod: read.headers()['x-served-by'] ?? null,
      });
      if (hidden === true) break;
      await tech.waitForTimeout(500);
    }
    console.log(
      'field-access diagnostics',
      JSON.stringify({
        tenant_admin: adminSession.tenant?.id ?? null,
        tenant_tech: techSession.tenant?.id ?? null,
        user_admin: adminSession.user.id,
        user_tech: techSession.user.id,
        rule_role_id: ruleRoleId ?? null,
        technician_role_id: technicianRoleId,
        tech_role_keys: techSession.user.roles ?? null,
        tech_user_read: techUserRead.status(),
        tech_role_ids: roleIds,
        tech_group_roles: groupRoles,
        polls,
      }),
    );
  } catch (error) {
    console.log('field-access diagnostics failed', String(error).slice(0, 200));
  }
}

/** Takes away the technician role's impact-details rule, if one is left (suite-owned). */
async function removeRule(admin: Page, roleId: string): Promise<void> {
  const listed = await call(admin, 'GET', `/field-access/rules?role_id=${roleId}`);
  for (const rule of (await listed.json()) as Rule[]) {
    // Every record type: a run that saved its rule on another type (the tab opened on Change, the
    // first type alphabetically) left one behind, and the next run's Hidden then saved nothing.
    if (rule.field === FIELD) {
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
    // The tab opens on the first record type alphabetically (Change): pick Incident, the record
    // the technician has open, or the rule lands on changes and the incident rightly keeps it.
    await admin.page.getByTestId('field-access-type').click();
    await admin.page.locator('.ant-select-item-option[title="Incident"]').click();
    await expect(admin.page.getByTestId('field-access-type')).toContainText('Incident');
    await admin.page.getByTestId(`field-access-mode-${FIELD}`).click();
    const posted = admin.page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().endsWith('/api/v1/field-access/rules'),
    );
    await admin.page.locator('.ant-select-item-option[title="Hidden"]').last().click();
    const rule = (await (await posted).json()) as { role_id?: string };
    await expect(admin.page.getByText('Field access saved')).toBeVisible();
    await logDiagnostics(admin.page, tech.page, incident.id, technician.id, rule.role_id);
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
