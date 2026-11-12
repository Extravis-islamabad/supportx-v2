import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-048b S4b: the workflows list (template C) and the designer (template A header + canvas).

const FLOW_ID = '01a1a2b3-0000-7000-8000-0000000f0001';
const LIVE_ID = '01a1a2b3-0000-7000-8000-0000000f0002';
const TENANT_CHANNEL = 't:tenant:queue:workflows';

const draft = {
  format: 1,
  nodes: [
    { id: 'start', type: 'start', config: {}, position: { x: 0, y: 0 } },
    { id: 'end', type: 'end', config: {}, position: { x: 0, y: 280 } },
  ],
  links: [{ from: 'start', port: 'next', to: 'end' }],
  variables: [],
};

const workflow = (over: Record<string, unknown> = {}) => ({
  id: FLOW_ID,
  record_type: 'incident',
  name: 'Major incident',
  description: null,
  enabled: false,
  published_version: null,
  running: 0,
  version: 3,
  draft,
  problems: [],
  start_templates: [],
  ...over,
});

const PALETTE = [
  {
    type: 'start',
    category: 'flow',
    available: true,
    why_not: null,
    outputs: ['next'],
    optional: [],
  },
  { type: 'end', category: 'flow', available: true, why_not: null, outputs: [], optional: [] },
  {
    type: 'if',
    category: 'logic',
    available: true,
    why_not: null,
    outputs: ['yes', 'no'],
    optional: [],
  },
  {
    type: 'notify',
    category: 'people',
    available: true,
    why_not: null,
    outputs: ['next', 'error'],
    optional: ['error'],
  },
  {
    type: 'function',
    category: 'actions',
    available: false,
    why_not: 'function_not_offered',
    outputs: ['next', 'error'],
    optional: ['error'],
  },
];

let restore: () => void = () => undefined;

/** Narrow (jsdom has no wide screen): the palette is the "Steps" tab, opened as a user would. */
async function palette(testId: string): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole('tab', { name: 'Steps' }));
  return screen.findByTestId(testId);
}
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

type Routes = NonNullable<Parameters<typeof consoleApi>[0]>['routes'];

function api(extra: Routes = {}) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['admin'] },
      {
        permissions: ['workflows.manage', 'workflows.run'].map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      'GET /api/v1/automation/workflows': {
        body: [
          workflow(),
          workflow({
            id: LIVE_ID,
            name: 'Escalation',
            running: 2,
            published_version: 1,
            enabled: true,
          }),
        ],
      },
      [`GET /api/v1/automation/workflows/${FLOW_ID}`]: {
        body: workflow(),
        headers: { ETag: '"3"' },
      },
      'GET /api/v1/automation/workflows/node-types': { body: PALETTE },
      'POST /api/v1/automation/workflows/node-ports': {
        body: [
          { outputs: ['next'], optional: [] },
          { outputs: [], optional: [] },
          { outputs: ['next', 'error'], optional: ['error'] },
        ],
      },
      'GET /api/v1/realtime/lists/workflows': { body: { channels: [TENANT_CHANNEL] } },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: workflows list', () => {
  it('lists a type’s workflows; one with live runs cannot be deleted, and says why', async () => {
    window.history.pushState({}, '', '/admin/workflows');
    api();
    render(<App />);
    await screen.findByText('Major incident');
    const table = screen.getByTestId('workflows-table');
    expect(table.textContent).toContain('Escalation');
    expect(table.textContent).toContain('Draft');
    expect(table.textContent).toContain('On');
    const more = within(table).getAllByRole('button', { name: /More actions/ })[1];
    if (more === undefined) throw new Error('no menu on the second row');
    fireEvent.click(more);
    const remove = await screen.findByTestId(`workflow-delete-${LIVE_ID}`);
    expect(
      remove.closest('[aria-disabled="true"], .ant-dropdown-menu-item-disabled'),
    ).not.toBeNull();
  });

  it('rule c: another admin’s change to a workflow refetches the list', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/admin/workflows');
    const fake = api();
    render(<App />);
    await screen.findByTestId('workflows-table');
    await waitFor(() => {
      expect(realtime.channels()).toContain(TENANT_CHANNEL);
    });
    const before = fake.find('GET', '/api/v1/automation/workflows').length;
    act(() => {
      realtime.publish(TENANT_CHANNEL, { type: 'workflows.changed', ids: [FLOW_ID], version: 4 });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/automation/workflows').length).toBeGreaterThan(before);
    });
  });
});

describe('console: workflow designer', () => {
  it('REQ-WF-008: a step added from the palette saves with the draft’s If-Match; undo takes it back', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api({
      [`PUT /api/v1/automation/workflows/${FLOW_ID}/draft`]: {
        body: workflow({ version: 4 }),
      },
    });
    render(<App />);
    expect((await screen.findByTestId('designer-header')).textContent).toContain('Major incident');
    await screen.findByTestId('node-start');
    const save = screen.getByTestId('designer-save');
    expect(save.hasAttribute('disabled')).toBe(true); // nothing to save yet
    fireEvent.click(await palette('palette-notify'));
    await screen.findByTestId('node-notify');
    expect(screen.getByTestId('designer-header').textContent).toContain('Unsaved changes');
    fireEvent.click(screen.getByTestId('designer-undo'));
    await waitFor(() => {
      expect(screen.queryByTestId('node-notify')).toBeNull();
    });
    fireEvent.click(screen.getByTestId('designer-redo'));
    await screen.findByTestId('node-notify');
    fireEvent.click(screen.getByTestId('designer-save'));
    await waitFor(() => {
      expect(fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`)).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`);
    expect(sent?.headers.get('If-Match')).toBe('"3"');
    const body = sent?.body as { definition: typeof draft };
    expect(body.definition.nodes.map((n) => [n.id, n.type])).toEqual([
      ['start', 'start'],
      ['end', 'end'],
      ['notify', 'notify'],
    ]);
    expect(body.definition.links).toEqual(draft.links);
  });

  it('REQ-WF-028 AC1: the outline links and unlinks outputs by keyboard', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api({
      [`PUT /api/v1/automation/workflows/${FLOW_ID}/draft`]: { body: workflow({ version: 4 }) },
    });
    render(<App />);
    await screen.findByTestId('node-start');
    fireEvent.click(await palette('palette-notify'));
    fireEvent.click(screen.getByRole('tab', { name: 'Outline' }));
    const outline = await screen.findByTestId('designer-outline');
    // start → notify instead of end; notify's "Next" → end.
    const pick = async (testId: string, option: string) => {
      const select = within(outline).getByTestId(testId);
      const box = select.querySelector('.ant-select-selector');
      if (box === null) throw new Error(`no select box in ${testId}`);
      fireEvent.mouseDown(box);
      const last = (await screen.findAllByTitle(option)).at(-1);
      if (last === undefined) throw new Error(`no option ${option}`);
      fireEvent.click(last);
    };
    await pick('outline-link-start-next', 'Send a notification');
    await pick('outline-link-notify-next', 'End');
    fireEvent.click(screen.getByTestId('designer-save'));
    await waitFor(() => {
      expect(fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`)).toHaveLength(1);
    });
    const [sent] = fake.find('PUT', `/api/v1/automation/workflows/${FLOW_ID}/draft`);
    const links = (sent?.body as { definition: typeof draft }).definition.links;
    expect(links).toEqual(
      expect.arrayContaining([
        { from: 'start', port: 'next', to: 'notify' },
        { from: 'notify', port: 'next', to: 'end' },
      ]),
    );
    expect(links).toHaveLength(2); // start's old link to end was replaced, not added to
  });

  it('REQ-WF-019: the draft’s problems mark their step, in words, and block publishing', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    api({
      [`GET /api/v1/automation/workflows/${FLOW_ID}`]: {
        body: workflow({
          problems: [{ where: 'node:end', code: 'node_unreachable', params: {} }],
        }),
        headers: { ETag: '"3"' },
      },
    });
    render(<App />);
    const end = await screen.findByTestId('node-end');
    expect(end.textContent).toContain('Problems to fix (1)');
    expect(screen.getByTestId('designer-problem-count').textContent).toBe('Problems (1)');
    expect(screen.getByTestId('designer-publish').hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('tab', { name: 'Problems (1)' }));
    const list = await screen.findByTestId('designer-problems');
    expect(list.textContent).not.toContain('node_unreachable'); // never a raw code
  });

  it('a step the record type cannot use now is shown disabled', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    api();
    render(<App />);
    const fn = await palette('palette-function');
    expect(fn.hasAttribute('disabled')).toBe(true);
  });
});
