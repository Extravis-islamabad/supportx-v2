import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-048b S5a: Admin › Workflows › Runs (template C; REQ-WF-025).

const FLOW = '01a1a2b3-0000-7000-8000-0000000f0501';
const SEEN = '01a1a2b3-0000-7000-8000-0000000f0502';
const HIDDEN = '01a1a2b3-0000-7000-8000-0000000f0503';
const JOB = '01a1a2b3-0000-7000-8000-0000000f0504';
const CHANNEL = 't:tenant:queue:workflows';

const run = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  workflow_id: FLOW,
  version_number: 1,
  record_type: 'incident',
  record_id: `${id.slice(0, -4)}aaaa`,
  status: 'failed',
  failure: { node: 'call', code: 'webhook_timeout', params: {} },
  wake_at: null,
  started_how: 'trigger',
  started_at: '2026-11-11T08:00:00Z',
  finished_at: null,
  stopped_reason: null,
  version: 3,
  workflow_name: 'Major incident',
  current_nodes: ['call'],
  record: null,
  ...over,
});

const job = (over: Record<string, unknown> = {}) => ({
  id: JOB,
  workflow_id: FLOW,
  kind: 'retry',
  status: 'running',
  total: 2,
  processed: 1,
  done_count: 1,
  skipped_count: 0,
  results: [],
  created_at: '2026-11-11T09:00:00Z',
  finished_at: null,
  version: 1,
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
      'GET /api/v1/automation/workflows/instances': {
        body: {
          items: [
            run(SEEN, { record: { display_id: 'INC-7', subject: 'Core switch down' } }),
            run(HIDDEN),
          ],
          next_cursor: null,
          has_more: false,
          estimated_total: 2,
        },
      },
      'GET /api/v1/automation/workflows': { body: [] },
      'GET /api/v1/realtime/lists/workflows': { body: { channels: [CHANNEL] } },
      [`GET /api/v1/automation/workflows/jobs/${JOB}`]: { body: job() },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: workflow runs', () => {
  it('names a record only when the viewer may see it, and failures in words', async () => {
    window.history.pushState({}, '', '/admin/workflows/runs');
    api();
    render(<App />);
    const table = await screen.findByTestId('runs-table');
    await within(table).findByText('Core switch down');
    expect(screen.getByTestId(`run-record-${SEEN}`).textContent).toContain('INC-7');
    expect(table.textContent).toContain("A record you can't see");
    expect(table.textContent).toContain('The other side took too long to answer.');
    expect(table.textContent).not.toContain('webhook_timeout');
  });

  it('REQ-WF-025 AC2: selected failed runs are retried as one job per workflow, live', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/admin/workflows/runs');
    const fake = api({
      [`POST /api/v1/automation/workflows/${FLOW}/jobs`]: { body: job(), status: 202 },
    });
    render(<App />);
    const table = await screen.findByTestId('runs-table');
    await within(table).findByText('Core switch down');
    const boxes = within(table).getAllByRole('checkbox');
    for (const box of boxes.slice(1)) fireEvent.click(box); // the two rows, not "select all"
    fireEvent.click(await screen.findByTestId('runs-retry'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`)).toHaveLength(1);
    });
    const [sent] = fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`);
    expect(sent?.body).toMatchObject({ kind: 'retry', instance_ids: [SEEN, HIDDEN] });
    expect(sent?.headers.get('Idempotency-Key')).not.toBeNull();
    const progress = await screen.findByTestId(`workflow-job-${JOB}`);
    expect(progress.textContent).toContain('1 done, 0 skipped, of 2');
    await waitFor(() => {
      expect(realtime.channels()).toContain(CHANNEL);
    });
    const before = fake.find('GET', `/api/v1/automation/workflows/jobs/${JOB}`).length;
    act(() => {
      realtime.publish(CHANNEL, { type: 'workflow_jobs.changed', ids: [JOB] });
    });
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/automation/workflows/jobs/${JOB}`).length).toBeGreaterThan(
        before,
      );
    });
  });

  it('cancelling asks why and sends the reason', async () => {
    window.history.pushState({}, '', '/admin/workflows/runs');
    const fake = api({
      [`POST /api/v1/automation/workflows/${FLOW}/jobs`]: {
        body: job({ kind: 'cancel' }),
        status: 202,
      },
    });
    render(<App />);
    const table = await screen.findByTestId('runs-table');
    await within(table).findByText('Core switch down');
    const first = within(table).getAllByRole('checkbox')[1];
    if (first === undefined) throw new Error('no row checkbox');
    fireEvent.click(first);
    fireEvent.click(await screen.findByTestId('runs-cancel'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByTestId('runs-cancel-reason'), {
      target: { value: 'Old process' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel runs' }));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`)).toHaveLength(1);
    });
    expect(fake.find('POST', `/api/v1/automation/workflows/${FLOW}/jobs`)[0]?.body).toMatchObject({
      kind: 'cancel',
      instance_ids: [SEEN],
      reason: 'Old process',
    });
  });
});
