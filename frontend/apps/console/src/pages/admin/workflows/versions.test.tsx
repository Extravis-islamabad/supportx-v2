import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-048b S5c: the designer's Versions tab and moving runs to the newest version (REQ-WF-021):
// a dry run first, the move only after it, both as jobs.

const FLOW = '01a1a2b3-0000-7000-8000-0000000f0601';
const DRY = '01a1a2b3-0000-7000-8000-0000000f0602';
const MOVE = '01a1a2b3-0000-7000-8000-0000000f0603';
const RUNS = ['0601', '0602', '0603'].map((n) => `01a1a2b3-0000-7000-8000-0000000f${n}a`);

const draft = {
  format: 1,
  nodes: [
    { id: 's', type: 'start', config: {}, position: { x: 0, y: 0 } },
    { id: 'hold', type: 'wait', config: {}, position: { x: 0, y: 140 } },
    { id: 'e', type: 'end', config: {}, position: { x: 0, y: 280 } },
  ],
  links: [],
  variables: [],
};

const job = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  workflow_id: FLOW,
  kind: 'migrate',
  status: 'done',
  total: 3,
  processed: 3,
  done_count: 0,
  skipped_count: 0,
  results: RUNS.map((r) => ({ instance_id: r, outcome: 'would_move' })),
  created_at: '2026-11-11T09:00:00Z',
  finished_at: '2026-11-11T09:00:01Z',
  version: 2,
  ...over,
});

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
      [`GET /api/v1/automation/workflows/${FLOW}`]: {
        body: {
          id: FLOW,
          record_type: 'incident',
          name: 'Major incident',
          description: null,
          enabled: true,
          published_version: 2,
          running: 3,
          version: 7,
          draft,
          problems: [],
          start_templates: [],
        },
        headers: { ETag: '"7"' },
      },
      'GET /api/v1/automation/workflows/node-types': { body: [] },
      'POST /api/v1/automation/workflows/node-ports': { body: [] },
      'GET /api/v1/realtime/lists/workflows': { body: { channels: [] } },
      [`GET /api/v1/automation/workflows/${FLOW}/versions`]: {
        body: [
          { number: 2, published_at: '2026-11-11T08:00:00Z', published_by: null, running: 0 },
          { number: 1, published_at: '2026-11-01T08:00:00Z', published_by: null, running: 3 },
        ],
      },
      [`GET /api/v1/automation/workflows/${FLOW}/versions/1/occupancy`]: { body: { w: 3 } },
      [`GET /api/v1/automation/workflows/${FLOW}/versions/2/steps`]: {
        body: [
          { id: 's', type: 'start' },
          { id: 'hold', type: 'wait' },
          { id: 'e', type: 'end' },
        ],
      },
      'GET /api/v1/automation/workflows/instances': {
        body: {
          items: RUNS.map((id) => ({
            id,
            workflow_id: FLOW,
            version_number: 1,
            record_type: 'incident',
            record_id: id,
            status: 'waiting',
            failure: null,
            wake_at: null,
            started_how: 'trigger',
            started_at: '2026-11-02T08:00:00Z',
            finished_at: null,
            stopped_reason: null,
            version: 2,
            workflow_name: 'Major incident',
            current_nodes: ['w'],
            record: null,
          })),
          next_cursor: null,
          has_more: false,
          estimated_total: 3,
        },
      },
      [`POST /api/v1/automation/workflows/${FLOW}/jobs`]: (call: { body: unknown }) => {
        const dry = (call.body as { dry_run: boolean }).dry_run;
        return { body: job(dry ? DRY : MOVE, dry ? {} : { status: 'running' }), status: 202 };
      },
      [`GET /api/v1/automation/workflows/jobs/${DRY}`]: { body: job(DRY) },
      [`GET /api/v1/automation/workflows/jobs/${MOVE}`]: {
        body: job(MOVE, { status: 'running', processed: 1 }),
      },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: workflow versions', () => {
  it('REQ-WF-021: map the occupied step, check first, then move', async () => {
    window.history.pushState({}, '', `/admin/workflows/${FLOW}`);
    const fake = api();
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Versions' }));
    const versions = await screen.findByTestId('workflow-versions');
    expect(versions.textContent).toContain('Live runs: 3');
    fireEvent.click(within(versions).getByTestId('version-1-move'));
    const dialog = await screen.findByTestId('version-move');
    const move = within(dialog.closest('.ant-modal') ?? dialog).getByRole('button', {
      name: 'Move runs (0)',
    });
    expect(move.hasAttribute('disabled')).toBe(true); // nothing checked yet
    // "w" is not in version 2: map it onto "hold".
    const select = await within(dialog).findByTestId('map-w');
    const box = select.closest('.ant-select')?.querySelector('.ant-select-selector');
    if (box === null || box === undefined) throw new Error('no select');
    fireEvent.mouseDown(box);
    const option = (await screen.findAllByTitle('Wait for a change')).at(-1);
    if (option === undefined) throw new Error('no option');
    fireEvent.click(option);
    fireEvent.click(within(dialog).getByTestId('version-dry-run'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`)).toHaveLength(1);
    });
    expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`)[0]?.body).toMatchObject({
      kind: 'migrate',
      to_version: 2,
      mapping: { w: 'hold' },
      dry_run: true,
      instance_ids: RUNS,
    });
    expect((await screen.findByTestId('version-dry-result')).textContent).toContain(
      'Would move: 3',
    );
    const ready = await screen.findByRole('button', { name: 'Move runs (3)' });
    await waitFor(() => {
      expect(ready.hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(ready);
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`)).toHaveLength(2);
    });
    expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`)[1]?.body).toMatchObject({
      kind: 'migrate',
      mapping: { w: 'hold' },
      dry_run: false,
    });
    await screen.findByTestId(`workflow-job-${MOVE}`); // the move's progress shows
  });
});
