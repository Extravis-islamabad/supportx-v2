import { expect, test, type Browser, type Page } from '@playwright/test';

import { USERS } from '../stack';
import { expectAccessible, resetLanguage, signInAs } from './helpers';

/**
 * WP-044a: problems, end to end.
 *
 * 1. A technician opens a problem from an incident: the form starts from the incident, a
 *    similar open problem shows while typing, and on save the incident is caused by the new
 *    problem. Assigned through the API, the owner shows live on the open record.
 * 2. A problem from the major problem template walks the guided analysis: the steps show, and
 *    the next moves run from the status bar.
 * 3. The problem pages in Arabic: right to left, accessible.
 *
 * Suite-owned data only: incidents, problems and the group are named "E2E …" and go with the
 * suite's teardown (tooling/e2e_fixtures.py).
 */

const LIVE = { timeout: 5_000 };

interface Made {
  id: string;
  display_id: string;
  version: number;
}

async function open(browser: Browser, user: 'admin' | 'tech', path: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await signInAs(page, user, path);
  await expect(page.locator('html')).toHaveAttribute('data-realtime-status', 'connected', LIVE);
  return { context, page };
}

/** The API as the page's signed-in user (same session cookie, CSRF header, If-Match). */
async function call(
  page: Page,
  method: string,
  path: string,
  { body, version }: { body?: unknown; version?: number } = {},
) {
  const base = new URL(page.url()).origin;
  const me = (await (await page.request.get(`${base}/api/v1/auth/me`)).json()) as {
    csrf_token: string;
  };
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token };
  if (version !== undefined) headers['If-Match'] = `"${String(version)}"`;
  if (method === 'POST') headers['Idempotency-Key'] = crypto.randomUUID();
  return page.request.fetch(`${base}/api/v1${path}`, { method, data: body, headers });
}

async function userId(page: Page): Promise<string> {
  const base = new URL(page.url()).origin;
  const me = (await (await page.request.get(`${base}/api/v1/auth/me`)).json()) as {
    user: { id: string };
  };
  return me.user.id;
}

/** An E2E group with the technician in it, so they work its problems (D-052). */
async function groupWith(admin: Page, name: string, memberId: string): Promise<string> {
  const group = await call(admin, 'POST', '/organization/groups', { body: { name } });
  expect(group.status(), await group.text()).toBe(201);
  const groupId = ((await group.json()) as { id: string }).id;
  const joined = await call(admin, 'PUT', `/organization/groups/${groupId}/members/${memberId}`);
  expect([200, 204]).toContain(joined.status());
  return groupId;
}

async function made(response: Awaited<ReturnType<typeof call>>): Promise<Made> {
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as Made;
}

test('a problem from an incident: prefilled, a similar one shown, linked, owner live', async ({
  browser,
}) => {
  const stamp = String(Date.now());
  const admin = await open(browser, 'admin', '/');
  const tech = await open(browser, 'tech', '/');
  const techId = await userId(tech.page);
  const groupId = await groupWith(admin.page, `E2E Problems ${stamp}`, techId);
  const incident = await made(
    await call(tech.page, 'POST', '/incidents', {
      body: { subject: `E2E Mail relay drops ${stamp}`, requester_id: techId, group_id: groupId },
    }),
  );
  // An open problem with a close title, to be offered while typing (REQ-PRB-014).
  const earlier = await made(
    await call(admin.page, 'POST', '/problems', {
      body: {
        subject: `E2E Mail relay drops messages ${stamp}`,
        requester_id: techId,
        group_id: groupId,
      },
    }),
  );

  await tech.page.goto(`/problems/new?incident=${incident.id}`);
  const subject = tech.page.getByTestId('prb-subject');
  await expect(subject).toHaveValue(`E2E Mail relay drops ${stamp}`);
  await expect(tech.page.getByTestId(`prb-similar-${earlier.display_id}`)).toBeVisible(LIVE);
  await subject.fill(`E2E Relay queue overflow ${stamp}`);
  await tech.page.getByTestId('prb-create').click();
  await expect(tech.page.getByTestId('prb-record')).toBeVisible(LIVE);
  await expect(tech.page.getByTestId('prb-incidents')).toContainText(incident.display_id);

  // Assigned elsewhere, the owner shows on the open record with no reload (§8).
  const problemId = tech.page.url().split('/').pop() ?? '';
  const current = (await (await call(admin.page, 'GET', `/problems/${problemId}`)).json()) as Made;
  const assigned = await call(admin.page, 'POST', `/problems/${problemId}/assign`, {
    body: { group_id: groupId, technician_id: techId },
    version: current.version,
  });
  expect(assigned.status(), await assigned.text()).toBe(200);
  await expect(tech.page.getByTestId('prb-panel')).toContainText(USERS.tech.last, LIVE);
  await tech.context.close();
  await admin.context.close();
});

test('the major problem template walks the guided analysis', async ({ browser }) => {
  const stamp = String(Date.now());
  const admin = await open(browser, 'admin', '/');
  const tech = await open(browser, 'tech', '/');
  const techId = await userId(tech.page);
  const groupId = await groupWith(admin.page, `E2E Major ${stamp}`, techId);
  const templates = (await (await call(tech.page, 'GET', '/problems/templates')).json()) as {
    id: string;
    code: string | null;
  }[];
  const major = templates.find((x) => x.code === 'major_problem');
  expect(major).toBeDefined();
  const problem = await made(
    await call(tech.page, 'POST', '/problems', {
      body: {
        subject: `E2E Datacentre outage ${stamp}`,
        requester_id: techId,
        group_id: groupId,
        template_id: major?.id,
      },
    }),
  );
  await tech.page.goto(`/problems/${problem.id}`);
  const steps = tech.page.getByTestId('prb-guided-steps');
  await expect(steps).toBeVisible(LIVE);
  await tech.page.getByRole('button', { name: 'Investigate' }).click();
  await expect(tech.page.getByTestId('inc-status')).toHaveAttribute(
    'data-status',
    'gathering_facts',
    LIVE,
  );
  await tech.page.getByRole('button', { name: 'Start the why-analysis' }).click();
  await expect(tech.page.getByTestId('inc-status')).toHaveAttribute(
    'data-status',
    'why_analysis',
    LIVE,
  );
  await tech.context.close();
  await admin.context.close();
});

test('the problem pages in Arabic are right to left and accessible', async ({ browser }) => {
  const tech = await open(browser, 'tech', '/');
  const techId = await userId(tech.page);
  const problem = await made(
    await call(tech.page, 'POST', '/problems', {
      body: { subject: `E2E مشكلة البريد ${String(Date.now())}`, requester_id: techId },
    }),
  );
  await tech.page.goto('/problems');
  await tech.page.getByTestId('appearance-menu').click();
  await tech.page.getByTestId('language-select').click();
  await tech.page.locator('.ant-select-item-option[title="العربية"]').click();
  await tech.page.getByTestId('appearance-menu').click();
  await expect(tech.page.locator('html')).toHaveAttribute('dir', 'rtl', LIVE);
  await expect(tech.page.getByTestId(`prb-row-${problem.display_id}`)).toBeVisible(LIVE);
  await expectAccessible(tech.page, 'problems list (ar)');
  await tech.page.goto(`/problems/${problem.id}`);
  await expect(tech.page.getByTestId('prb-record')).toBeVisible(LIVE);
  await expectAccessible(tech.page, 'problem record (ar)');
  await resetLanguage(tech.page);
  await tech.context.close();
});
