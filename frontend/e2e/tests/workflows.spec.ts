import { expect, test, type Page } from '@playwright/test';

import { deleteE2eRoles, expectAccessible, openSelect, resetLanguage, signInAs } from './helpers';

// WP-048b S5e, visual workflows end to end (REQ-WF-008, -022, -023, -024):
// 1. a workflow built in the designer by keyboard (palette buttons and the outline), published,
//    started on an incident and seen on its Workflows tab;
// 2. test mode on sample values, its timer moved on;
// 3. a run that fails, skipped from the incident's Workflows tab.
// None of them waits on the background worker, so they hold in every stack. A webhook that
// fails at its receiver needs the worker and a receiver: not a journey here (PROGRESS.md).
// Every workflow and incident made here is deleted afterwards.

const LIVE = { timeout: 15_000 };
const BASE = '/api/v1/automation/workflows';

interface Me {
  csrf_token: string;
  user: { id: string };
}

async function me(page: Page): Promise<Me> {
  return (await (await page.request.get('/api/v1/auth/me')).json()) as Me;
}

async function incident(page: Page, subject: string): Promise<string> {
  const { csrf_token, user } = await me(page);
  const made = await page.request.post('/api/v1/incidents', {
    data: { subject, requester_id: user.id, description: `<p>${subject}</p>` },
    headers: { 'X-CSRF-Token': csrf_token },
  });
  expect(made.status(), await made.text()).toBe(201);
  return ((await made.json()) as { id: string }).id;
}

async function removeIncident(page: Page, id: string): Promise<void> {
  const { csrf_token } = await me(page);
  const found = await page.request.get(`/api/v1/incidents/${id}`);
  if (found.status() !== 200) return;
  const { version } = (await found.json()) as { version: number };
  await page.request.delete(`/api/v1/incidents/${id}`, {
    headers: { 'If-Match': `"${String(version)}"`, 'X-CSRF-Token': csrf_token },
  });
}

interface Flow {
  id: string;
  version: number;
}

/** A workflow made, saved, published and switched on through the API (journeys 2 and 3). */
async function workflow(page: Page, name: string, definition: object, publish: boolean) {
  const { csrf_token } = await me(page);
  const write = { 'X-CSRF-Token': csrf_token };
  const made = await page.request.post(BASE, {
    data: { record_type: 'incident', name },
    headers: { ...write, 'Idempotency-Key': crypto.randomUUID() },
  });
  expect(made.status(), await made.text()).toBe(201);
  let flow = (await made.json()) as Flow;
  const step = async (method: 'put' | 'post', path: string, data?: object) => {
    const response = await page.request[method](`${BASE}/${flow.id}${path}`, {
      data,
      headers: { ...write, 'If-Match': `"${String(flow.version)}"` },
    });
    expect(response.status(), await response.text()).toBe(200);
    flow = (await response.json()) as Flow;
  };
  await step('put', '/draft', { definition });
  if (publish) {
    await step('post', '/publish');
    await step('put', '/enabled', { enabled: true });
  }
  return flow.id;
}

async function start(page: Page, flow: string, record: string): Promise<void> {
  const { csrf_token } = await me(page);
  const started = await page.request.post(`${BASE}/${flow}/instances`, {
    data: { record_id: record },
    headers: { 'X-CSRF-Token': csrf_token, 'Idempotency-Key': crypto.randomUUID() },
  });
  expect(started.status(), await started.text()).toBe(201);
}

/** Delete a workflow made here; one with live runs is switched off and left (never forced). */
async function removeWorkflow(page: Page, id: string): Promise<void> {
  const { csrf_token } = await me(page);
  const found = await page.request.get(`${BASE}/${id}`);
  if (found.status() !== 200) return;
  const { version } = (await found.json()) as { version: number };
  await page.request.delete(`${BASE}/${id}`, {
    headers: { 'If-Match': `"${String(version)}"`, 'X-CSRF-Token': csrf_token },
  });
}

/**
 * Give the workflow's run-as identity a role that reaches every incident and adds notes, through
 * its own guarded route (the coordinator, 2026-11-11: publishing gives it none). The role is the
 * suite's own ("E2E …"), removed by `deleteE2eRoles`.
 */
async function giveRunAsRole(page: Page, flow: string): Promise<void> {
  const { csrf_token } = await me(page);
  const write = { 'X-CSRF-Token': csrf_token };
  const role = await page.request.post('/api/v1/roles', {
    data: {
      name: `E2E workflow notes ${String(Date.now())}`,
      permissions: [
        { permission: 'incidents.view', scope: 'all' },
        { permission: 'incidents.add_note', scope: 'all' },
      ],
    },
    headers: write,
  });
  expect(role.status(), await role.text()).toBe(201);
  const { id } = (await role.json()) as { id: string };
  const given = await page.request.put(`${BASE}/${flow}/run-as/roles/${id}`, { headers: write });
  expect(given.status(), await given.text()).toBe(204);
}

/** The signed-in user's language, stored as theirs (put back by `resetLanguage`). */
async function useLanguage(page: Page, locale: string): Promise<void> {
  const { csrf_token, user } = await me(page);
  const path = `/api/v1/users/${user.id}`;
  const current = (await (await page.request.get(path)).json()) as { version: number };
  const saved = await page.request.patch(path, {
    data: { ui_locale: locale },
    headers: { 'If-Match': `"${String(current.version)}"`, 'X-CSRF-Token': csrf_token },
  });
  expect(saved.status(), await saved.text()).toBe(200);
}

const at = (x: number, y: number) => ({ x, y });

test('REQ-WF-008, -028: a workflow built by keyboard, published, run on an incident', async ({
  page,
}) => {
  await signInAs(page, 'admin', '/admin/workflows');
  const name = `E2E keyboard ${String(Date.now())}`;
  let flow = '';
  let record = '';
  try {
    await page.getByTestId('workflows-add').click();
    await page.getByTestId('workflow-name').fill(name);
    await page.getByRole('button', { name: 'Add workflow' }).last().click();
    await expect(page.getByTestId('workflow-designer')).toBeVisible(LIVE);
    flow = page.url().split('/').at(-1) ?? '';
    await expect(page.getByTestId('node-start')).toBeVisible(LIVE);

    // A note step from the palette's button (no drag), then its settings in Advanced.
    const steps = page.getByRole('tab', { name: 'Steps' });
    if (await steps.isVisible()) await steps.click();
    await page.getByTestId('palette-note').click();
    await expect(page.getByTestId('node-note')).toBeVisible();
    await page.getByRole('tab', { name: 'Details' }).click();
    await page.getByText('Advanced').click();
    await page.getByTestId('designer-node-config').fill('{"text": {"en": "E2E workflow note"}}');
    await page.getByTestId('designer-node-apply').click();

    // The outline: start → note → end, by its selects alone.
    await page.getByRole('tab', { name: 'Outline' }).click();
    let list = await openSelect(page, 'outline-link-start-next');
    await list.getByTitle('Add a note (note)').click();
    list = await openSelect(page, 'outline-link-note-next');
    await list.getByTitle('End (end)').click();
    await expectAccessible(page, 'the workflow designer');

    await page.getByTestId('designer-save').click();
    await expect(page.getByTestId('designer-problem-count')).toHaveCount(0, LIVE);
    // A note acts as the workflow's run-as identity, which has no role yet: the canvas says so
    // (in Arabic too), and publishing asks first.
    const warning = page.getByTestId('designer-run-as-warning');
    await expect(warning).toContainText("This workflow can't change records yet", LIVE);
    await useLanguage(page, 'ar');
    await page.reload();
    await expect(page.getByTestId('designer-run-as-warning')).toContainText(
      'لا يستطيع سير العمل هذا تغيير السجلات بعد',
      LIVE,
    );
    await resetLanguage(page);
    await page.reload();
    await page.getByTestId('designer-publish').click();
    const confirm = page.getByRole('dialog');
    await expect(confirm).toContainText('Publish without a role?');
    await confirm.getByRole('button', { name: 'Publish anyway' }).click();
    await expect(page.getByTestId('designer-header')).toContainText('Version 1', LIVE);
    // Given a role, the warning goes, live.
    await giveRunAsRole(page, flow);
    await expect(warning).toHaveCount(0, LIVE);
    await page.getByTestId('designer-actions-more').click();
    await page.getByTestId('designer-enable').click();
    await expect(page.getByTestId('designer-header')).toContainText('On', LIVE);

    record = await incident(page, `E2E workflow run ${String(Date.now())}`);
    await start(page, flow, record);
    await page.goto(`/incidents/${record}`);
    await page.getByRole('tab', { name: 'Workflows' }).click();
    const panel = page.getByTestId('record-workflows');
    await expect(panel).toContainText(name, LIVE);
    await expect(panel).toContainText('Finished');
    await expectAccessible(page, "an incident's Workflows tab");
  } finally {
    await resetLanguage(page);
    if (record !== '') await removeIncident(page, record);
    if (flow !== '') await removeWorkflow(page, flow);
    await deleteE2eRoles(page);
  }
});

test('REQ-WF-022 AC3: a test run on sample values moves its timer on', async ({ page }) => {
  await signInAs(page, 'admin', '/admin/workflows');
  const flow = await workflow(
    page,
    `E2E timer ${String(Date.now())}`,
    {
      format: 1,
      nodes: [
        { id: 'start', type: 'start', config: {}, position: at(0, 0) },
        { id: 'pause', type: 'timer', config: { seconds: 3600 }, position: at(0, 140) },
        { id: 'end', type: 'end', config: {}, position: at(0, 280) },
      ],
      links: [
        { from: 'start', port: 'next', to: 'pause' },
        { from: 'pause', port: 'next', to: 'end' },
      ],
      variables: [],
    },
    false,
  );
  try {
    await page.goto(`/admin/workflows/${flow}`);
    await page.getByRole('tab', { name: 'Test' }).click();
    await page.getByLabel('Sample values').check();
    await page.getByTestId('test-run').click();
    await expect(page.getByTestId('test-status')).toHaveText('Waiting', LIVE);
    await expect(page.getByTestId('node-pause')).toHaveAttribute('data-state', 'current');
    await page.getByTestId('test-forward').fill('1');
    await page.getByTestId('test-forward-send').click();
    await expect(page.getByTestId('test-status')).toHaveText('Finished', LIVE);
  } finally {
    await removeWorkflow(page, flow);
  }
});

test('REQ-WF-024 AC2: a failed step is skipped from the incident, with a confirm', async ({
  page,
}) => {
  await signInAs(page, 'admin', '/admin/workflows');
  // A field step its run-as identity may not do (it holds no role): the run fails there, in
  // words, and is skipped from the incident.
  const flow = await workflow(
    page,
    `E2E skip ${String(Date.now())}`,
    {
      format: 1,
      nodes: [
        { id: 'start', type: 'start', config: {}, position: at(0, 0) },
        {
          id: 'set',
          type: 'field_update',
          config: { values: { impact: 'team' } },
          position: at(0, 140),
        },
        { id: 'end', type: 'end', config: {}, position: at(0, 280) },
      ],
      links: [
        { from: 'start', port: 'next', to: 'set' },
        { from: 'set', port: 'next', to: 'end' },
      ],
      variables: [],
    },
    true,
  );
  const record = await incident(page, `E2E workflow skip ${String(Date.now())}`);
  try {
    await start(page, flow, record);
    await page.goto(`/incidents/${record}`);
    await page.getByRole('tab', { name: 'Workflows' }).click();
    const panel = page.getByTestId('record-workflows');
    await expect(panel).toContainText('Failed', LIVE);
    await expect(panel).toContainText('Stopped at the step set');
    await expect(panel).toContainText(
      "The workflow's run-as identity has no right to do this step",
    );
    await panel.getByRole('button', { name: 'Skip this step' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('recorded with your name');
    await dialog.getByRole('button', { name: 'Skip this step' }).click();
    await expect(panel).toContainText('Finished', LIVE);
  } finally {
    await removeIncident(page, record);
    await removeWorkflow(page, flow);
  }
});
