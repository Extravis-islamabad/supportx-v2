import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// QA F-05: the steps that were JSON only have forms too. Each test opens a step
// from the outline (the keyboard path), fills its form, applies and saves, and checks the
// config the server receives is the one the definition stores.

const FLOW_ID = '01a1a2b3-0000-7000-8000-0000000f0101';
const GROUP_ID = '01a1a2b3-0000-7000-8000-0000000f0201';

const node = (id: string, type: string, config: Record<string, unknown> = {}) => ({
  id,
  type,
  config,
  position: { x: 0, y: 0 },
});

const draft = {
  format: 1,
  nodes: [
    node('start', 'start'),
    node('check', 'if'),
    node('route', 'switch', { cases: [] }),
    node('tell', 'notify'),
    node('pause', 'timer', { seconds: 3600 }),
    node('hold', 'wait', { events: [] }),
    node('move', 'set_status'),
    node('ok', 'approval'),
    node('fill', 'field_update'),
    node('call', 'webhook'),
    node('keep', 'set_variable'),
    node('end', 'end'),
  ],
  links: [],
  variables: [{ name: 'status_code', kind: 'number' }],
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

function api() {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['admin'] },
      {
        permissions: ['workflows.manage'].map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      [`GET /api/v1/automation/workflows/${FLOW_ID}`]: {
        body: {
          id: FLOW_ID,
          record_type: 'incident',
          name: 'Forms',
          description: null,
          enabled: false,
          published_version: null,
          running: 0,
          version: 5,
          draft,
          problems: [],
          start_templates: [],
        },
        headers: { ETag: '"5"' },
      },
      'GET /api/v1/automation/workflows/node-types': {
        body: [
          {
            type: 'approval',
            category: 'people',
            available: true,
            why_not: null,
            outputs: ['approved', 'rejected'],
            optional: [],
            roles: ['change_owner', 'requester'],
          },
        ],
      },
      'POST /api/v1/automation/workflows/node-ports': { body: [] },
      'GET /api/v1/automation/fields': {
        body: [
          { name: 'priority', kind: 'code', derived: false, settable: true, values: ['p1', 'p2'] },
          { name: 'due_at', kind: 'datetime', derived: false, settable: true, values: null },
        ],
      },
      'GET /api/v1/organization/groups': {
        body: [{ id: GROUP_ID, name: 'Network', kind: 'group' }],
      },
      'GET /api/v1/realtime/lists/workflows': { body: { channels: [] } },
      [`PUT /api/v1/automation/workflows/${FLOW_ID}/draft`]: { body: {} },
    },
  });
  restore = fake.restore;
  return fake;
}

/** Open a step's details from the outline, as a keyboard user does. */
async function open(id: string) {
  fireEvent.click(await screen.findByRole('tab', { name: 'Outline' }));
  const outline = await screen.findByTestId('designer-outline');
  const [button] = within(within(outline).getByTestId(`outline-${id}`)).getAllByRole('button');
  if (button === undefined) throw new Error(`no button for ${id}`);
  fireEvent.click(button);
  return screen.findByTestId('designer-node-details');
}

async function choose(container: HTMLElement, testId: string, option: string) {
  const box = within(container)
    .getByTestId(testId)
    .closest('.ant-select')
    ?.querySelector('.ant-select-selector');
  if (box === null || box === undefined) throw new Error(`no select ${testId}`);
  fireEvent.mouseDown(box);
  const last = (await screen.findAllByTitle(option)).at(-1);
  if (last === undefined) throw new Error(`no option ${option}`);
  fireEvent.click(last);
}

/** Apply, save, and the config the server got for one step. */
async function saved(fake: ReturnType<typeof api>, id: string) {
  fireEvent.click(screen.getByTestId('designer-node-apply'));
  fireEvent.click(screen.getByTestId('designer-save'));
  await waitFor(() => {
    expect(fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`)).toHaveLength(1);
  });
  const [sent] = fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`);
  const body = sent?.body as { definition: typeof draft };
  return body.definition.nodes.find((n) => n.id === id)?.config;
}

describe('console: workflow node forms (QA F-05)', () => {
  it('approval: the record’s roles by name, groups and the rule', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('ok');
    await choose(details, 'approval-roles', 'Change owner');
    await choose(details, 'approval-groups', 'Network');
    fireEvent.click(within(details).getByLabelText('A majority'));
    expect(await saved(fake, 'ok')).toEqual({
      approvers: { user_ids: [], group_ids: [GROUP_ID], roles: ['change_owner'] },
      rule: 'majority',
    });
  });

  it('field update: a field and its value per row', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('fill');
    // The settable fields come from the server first.
    await waitFor(() => {
      expect(within(details).getByTestId('set-field-add')).not.toHaveProperty('disabled', true);
    });
    fireEvent.click(within(details).getByTestId('set-field-add'));
    expect(await within(details).findByTestId('set-field-1-field')).toBeTruthy();
    expect(await saved(fake, 'fill')).toEqual({ values: { priority: null } });
  });

  it('webhook: address, request type, fields sent, a header and the status kept', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('call');
    fireEvent.change(within(details).getByTestId('webhook-url'), {
      target: { value: 'https://hooks.example.com/x ' },
    });
    fireEvent.click(within(details).getByLabelText('PUT (replace)'));
    fireEvent.click(within(details).getByTestId('webhook-header-add'));
    fireEvent.change(within(details).getByTestId('webhook-header-1-name'), {
      target: { value: 'X-Team' },
    });
    fireEvent.change(within(details).getByTestId('webhook-header-1-value'), {
      target: { value: 'ops' },
    });
    await choose(details, 'webhook-status', 'status_code');
    expect(await saved(fake, 'call')).toEqual({
      url: 'https://hooks.example.com/x',
      method: 'PUT',
      headers: { 'X-Team': 'ops' },
      status_variable: 'status_code',
    });
  });

  it('set variable: a declared variable and a fixed value of its kind', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('keep');
    await choose(details, 'set-variable', 'status_code');
    fireEvent.change(within(details).getByTestId('variable-value'), { target: { value: '7' } });
    expect(await saved(fake, 'keep')).toEqual({ variable: 'status_code', value: 7 });
  });

  it('the Variables tab adds a variable that is saved with the draft, and refuses a bad name', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Variables' }));
    const panel = await screen.findByTestId('designer-variables');
    fireEvent.click(within(panel).getByTestId('variable-add'));
    fireEvent.change(within(panel).getByTestId('variable-2-name'), {
      target: { value: 'status code' },
    });
    expect(within(panel).getByText('Use letters, digits, _ and - only.')).toBeTruthy();
    fireEvent.change(within(panel).getByTestId('variable-2-name'), {
      target: { value: 'replies' },
    });
    fireEvent.click(screen.getByTestId('designer-save'));
    await waitFor(() => {
      expect(fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`)).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`);
    expect((sent?.body as { definition: typeof draft }).definition.variables).toEqual([
      { name: 'status_code', kind: 'number' },
      { name: 'replies', kind: 'text' },
    ]);
  });
});
