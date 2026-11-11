import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-048b S4c: test mode in the designer (REQ-WF-022). The run's answers go to the server with
// the run's If-Match; the path taken and where the run is are marked on the canvas; the one live
// call is confirmed first.

const FLOW_ID = '01a1a2b3-0000-7000-8000-0000000f0301';
const RUN_ID = '01a1a2b3-0000-7000-8000-0000000f0302';
const RECORD_ID = '01a1a2b3-0000-7000-8000-0000000f0303';

beforeAll(() => {
  if (!('ResizeObserver' in window)) {
    // jsdom has no layout: React Flow watches its pane's size, which never changes here.
    class NoResize {
      observe = () => undefined;
      unobserve = () => undefined;
      disconnect = () => undefined;
    }
    Object.assign(window, { ResizeObserver: NoResize });
  }
});

const node = (id: string, type: string) => ({ id, type, config: {}, position: { x: 0, y: 0 } });
const draft = {
  format: 1,
  nodes: [
    node('start', 'start'),
    node('ask', 'approval'),
    node('call', 'webhook'),
    node('end', 'end'),
  ],
  links: [
    { from: 'start', port: 'next', to: 'ask' },
    { from: 'ask', port: 'approved', to: 'call' },
    { from: 'call', port: 'next', to: 'end' },
  ],
  variables: [],
};

const run = (over: Record<string, unknown> = {}) => ({
  id: RUN_ID,
  workflow_id: FLOW_ID,
  record_id: null,
  status: 'waiting',
  facts: {},
  variables: {},
  steps: [
    {
      token: 't1',
      node: 'start',
      node_type: 'start',
      result: 'next',
      at: '2026-11-11T10:00:00Z',
      detail: {},
    },
  ],
  pending: [{ id: 'c1', node: 'ask', kind: 'open_approval', payload: {} }],
  current_nodes: ['ask'],
  clock_at: '2026-11-11T10:00:00Z',
  live_call: null,
  version: 2,
  ...over,
});

let restore: () => void = () => undefined;
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
          record_type: 'release',
          name: 'Release approval',
          description: null,
          enabled: false,
          published_version: null,
          running: 0,
          version: 2,
          draft,
          problems: [],
          start_templates: [],
        },
        headers: { ETag: '"2"' },
      },
      'GET /api/v1/automation/workflows/node-types': { body: [] },
      'POST /api/v1/automation/workflows/node-ports': { body: [] },
      'GET /api/v1/realtime/lists/workflows': { body: { channels: [] } },
      [`POST /api/v1/automation/workflows/${FLOW_ID}/test-runs`]: { body: run(), status: 201 },
      [`GET /api/v1/automation/workflows/test-runs/${RUN_ID}`]: { body: run() },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

async function openTest() {
  fireEvent.click(await screen.findByRole('tab', { name: 'Test' }));
  return screen.findByTestId('test-start');
}

describe('console: workflow test mode', () => {
  it('REQ-WF-022 AC1: a run on sample values; "Approved" goes with the run’s If-Match and the path is marked', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api({
      [`POST /api/v1/automation/workflows/test-runs/${RUN_ID}/answer`]: {
        body: run({
          status: 'waiting',
          pending: [{ id: 'c2', node: 'call', kind: 'call_webhook', payload: {} }],
          current_nodes: ['call'],
          version: 3,
        }),
      },
    });
    render(<App />);
    const start = await openTest();
    fireEvent.click(within(start).getByLabelText('Sample values'));
    fireEvent.change(within(start).getByTestId('test-sample'), {
      target: { value: '{"priority": "p1"}' },
    });
    fireEvent.click(within(start).getByTestId('test-run'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW_ID}/test-runs`)).toHaveLength(
        1,
      );
    });
    const [started] = fake.find('POST', `/api/v1/automation/workflows/${FLOW_ID}/test-runs`);
    expect(started?.body).toEqual({ sample: { priority: 'p1' } });
    expect(started?.headers.get('Idempotency-Key')).not.toBeNull();
    await waitFor(() => {
      expect(screen.getByTestId('node-ask').getAttribute('data-state')).toBe('current');
    });
    expect(screen.getByTestId('node-start').getAttribute('data-state')).toBe('passed');
    fireEvent.click(await screen.findByTestId('test-ok-ask'));
    await waitFor(() => {
      expect(
        fake.find('POST', `/api/v1/automation/workflows/test-runs/${RUN_ID}/answer`),
      ).toHaveLength(1);
    });
    const [answered] = fake.find('POST', `/api/v1/automation/workflows/test-runs/${RUN_ID}/answer`);
    expect(answered?.headers.get('If-Match')).toBe('"2"');
    expect(answered?.body).toEqual({ command_id: 'c1', ok: true, port: 'approved' });
    // A run on sample values has no record: no live call is offered.
    await screen.findByTestId('test-command-call');
    expect(screen.queryByTestId('test-live-call')).toBeNull();
  });

  it('the one live call on a record is confirmed first, saying it is audited', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const onRecord = run({
      record_id: RECORD_ID,
      pending: [{ id: 'c2', node: 'call', kind: 'call_webhook', payload: {} }],
      current_nodes: ['call'],
    });
    const fake = api({
      'GET /api/v1/releases/lookup/REL-4': { body: { id: RECORD_ID } },
      [`POST /api/v1/automation/workflows/${FLOW_ID}/test-runs`]: { body: onRecord, status: 201 },
      [`GET /api/v1/automation/workflows/test-runs/${RUN_ID}`]: { body: onRecord },
      [`POST /api/v1/automation/workflows/test-runs/${RUN_ID}/live-call`]: {
        body: { ...onRecord, live_call: { node: 'call' }, version: 3 },
      },
    });
    render(<App />);
    const start = await openTest();
    fireEvent.change(within(start).getByTestId('test-record'), { target: { value: 'REL-4' } });
    fireEvent.click(within(start).getByTestId('test-run'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW_ID}/test-runs`)).toHaveLength(
        1,
      );
    });
    expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW_ID}/test-runs`)[0]?.body).toEqual(
      {
        record_id: RECORD_ID,
      },
    );
    fireEvent.click(await screen.findByTestId('test-live-call'));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('audit trail');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Run it' }));
    await waitFor(() => {
      expect(
        fake.find('POST', `/api/v1/automation/workflows/test-runs/${RUN_ID}/live-call`),
      ).toHaveLength(1);
    });
    expect(
      fake.find('POST', `/api/v1/automation/workflows/test-runs/${RUN_ID}/live-call`)[0]?.body,
    ).toEqual({
      command_id: 'c2',
    });
  });

  it('REQ-WF-022 AC3: the clock moves on in hours', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW_ID}`);
    const fake = api({
      [`POST /api/v1/automation/workflows/test-runs/${RUN_ID}/answer`]: {
        body: run({ version: 3 }),
      },
    });
    render(<App />);
    const start = await openTest();
    fireEvent.click(within(start).getByLabelText('Sample values'));
    fireEvent.click(within(start).getByTestId('test-run'));
    fireEvent.change(await screen.findByTestId('test-forward'), { target: { value: '2' } });
    fireEvent.click(screen.getByTestId('test-forward-send'));
    await waitFor(() => {
      expect(
        fake.find('POST', `/api/v1/automation/workflows/test-runs/${RUN_ID}/answer`),
      ).toHaveLength(1);
    });
    expect(
      fake.find('POST', `/api/v1/automation/workflows/test-runs/${RUN_ID}/answer`)[0]?.body,
    ).toEqual({
      ok: true,
      fast_forward_seconds: 7200,
    });
  });
});
