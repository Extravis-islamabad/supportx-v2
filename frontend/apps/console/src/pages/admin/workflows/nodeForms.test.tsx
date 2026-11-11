import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-048b S4b: the settings forms of the node types people use most. Each test opens a step
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
    node('end', 'end'),
  ],
  links: [],
  variables: [],
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
      'GET /api/v1/automation/workflows/node-types': { body: [] },
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
async function open(id: string, label: string) {
  fireEvent.click(await screen.findByRole('tab', { name: 'Outline' }));
  const outline = await screen.findByTestId('designer-outline');
  fireEvent.click(
    within(within(outline).getByTestId(`outline-${id}`)).getByRole('button', { name: label }),
  );
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

describe('console: workflow node forms', () => {
  it('if: a condition on the record’s fields, stored as the rules grammar', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('check', 'If');
    fireEvent.click(within(details).getByTestId('condition-add'));
    await choose(details, 'condition-0-field', 'Priority');
    await choose(details, 'condition-0-op', 'is empty');
    expect(await saved(fake, 'check')).toEqual({ condition: { field: 'priority', op: 'is_null' } });
  });

  it('switch: named cases, each with its condition', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('route', 'Switch');
    fireEvent.click(within(details).getByTestId('switch-add-case'));
    fireEvent.change(within(details).getByTestId('switch-case-0-port'), {
      target: { value: 'urgent' },
    });
    expect(await saved(fake, 'route')).toEqual({ cases: [{ port: 'urgent', condition: null }] });
  });

  it('notify: the record’s people, groups, subject and message in each language', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('tell', 'Send a notification');
    fireEvent.click(within(details).getByLabelText('Requester'));
    await choose(details, 'notify-groups', 'Network');
    fireEvent.change(within(within(details).getByTestId('notify-subject')).getByRole('textbox'), {
      target: { value: 'Major incident' },
    });
    expect(await saved(fake, 'tell')).toMatchObject({
      audience: { relatives: ['requester'], group_ids: [GROUP_ID] },
      subject: { en: 'Major incident' },
    });
  });

  it('timer: a length of time in hours, or a date on the record', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('pause', 'Timer');
    const amount = within(details).getByTestId('timer-seconds');
    expect((amount as HTMLInputElement).value).toBe('1'); // 3600 s shows as 1 hour
    fireEvent.change(amount, { target: { value: '4' } });
    expect(await saved(fake, 'pause')).toEqual({ seconds: 14_400 });
  });

  it('wait: what it listens for, and a time limit that adds the Timed out output', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('hold', 'Wait for a change');
    await choose(details, 'wait-events', 'The requester replied');
    fireEvent.click(within(details).getByTestId('wait-has-limit'));
    expect(await saved(fake, 'hold')).toEqual({
      events: ['requester_replied'],
      limit_seconds: 86_400,
    });
  });

  it('set status: the status move, by name', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api();
    render(<App />);
    const details = await open('move', 'Set status');
    await choose(details, 'status-action', 'Resolve');
    expect(await saved(fake, 'move')).toEqual({ action: 'resolve' });
  });

  it('a type without a form opens Advanced, its settings as stored', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    api();
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Outline' }));
    const outline = await screen.findByTestId('designer-outline');
    fireEvent.click(
      within(within(outline).getByTestId('outline-end')).getByRole('button', { name: 'End' }),
    );
    const details = await screen.findByTestId('designer-node-details');
    expect(within(details).queryByTestId('designer-node-config')).toBeNull(); // the end has none
  });
});
