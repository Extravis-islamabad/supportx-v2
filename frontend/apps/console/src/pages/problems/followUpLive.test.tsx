// QA10-P1-09: a problem's follow-up progress is live off the incidents list too. The personal
// channel is captured here, so the test can say "the job moved" as the server would.
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../App';
import { clickAction } from '../../test/actions';
import { consoleApi } from '../../test/api';

interface Message {
  type: string;
  ids: string[];
}
const personal: ((message: Message) => void)[] = [];

vi.mock('@supportx/realtime', async (actual) => ({
  ...(await actual<typeof import('@supportx/realtime')>()),
  usePersonalChannel: (handler: (message: Message) => void) => {
    personal.push(handler);
  },
}));

const PRB_ID = '01a1a2b3-0000-7000-8000-00000000e001';
const INC_ID = '01a1a2b3-0000-7000-8000-00000000c101';
const JOB_ID = '01a1a2b3-0000-7000-8000-00000000d001';

function job(status: 'queued' | 'done') {
  return {
    id: JOB_ID,
    action: 'resolve',
    status,
    total: 1,
    processed: status === 'done' ? 1 : 0,
    done_count: status === 'done' ? 1 : 0,
    skipped_count: 0,
    results: [],
    created_at: '2026-11-10T08:00:00Z',
    started_at: null,
    finished_at: status === 'done' ? '2026-11-10T08:00:05Z' : null,
  };
}

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  personal.length = 0;
});

describe('follow-up progress', () => {
  it('QA10-P1-09: the drawer moves on when the channel says the job moved', async () => {
    let status: 'queued' | 'done' = 'queued';
    const record = fakeIncident({ id: PRB_ID, type: 'problem', display_id: 'PRB-6' });
    const fake = consoleApi({
      routes: {
        'GET /api/v1/problems/settings': { body: fakeIncidentCatalogue() },
        [`GET /api/v1/problems/${PRB_ID}`]: { body: record },
        [`GET /api/v1/problems/${PRB_ID}/links`]: { body: [] },
        [`GET /api/v1/problems/${PRB_ID}/investigators`]: { body: { user_ids: [], people: {} } },
        [`GET /api/v1/problems/${PRB_ID}/follow-up`]: {
          body: {
            incidents: [{ id: INC_ID, display_id: 'INC-63', subject: 'VPN drops' }],
            has_resolution: true,
            has_workaround: false,
          },
        },
        [`POST /api/v1/problems/${PRB_ID}/follow-up`]: { status: 202, body: job('queued') },
        [`GET /api/v1/incidents/bulk-jobs/${JOB_ID}`]: () => ({ body: job(status) }),
      },
    });
    restore = fake.restore;
    window.history.pushState({}, '', `/problems/${PRB_ID}`);
    render(<App />);
    await clickAction('prb-op-follow-up', 'prb-actions');
    await screen.findByTestId('prb-follow-up-INC-63');
    fireEvent.click(screen.getByTestId('prb-follow-up-start'));
    const drawer = await screen.findByTestId('inc-bulk-progress');
    expect((await within(drawer).findByTestId('inc-bulk-status')).textContent).toBe(
      'Waiting to start…',
    );
    status = 'done';
    act(() => {
      for (const handler of personal) handler({ type: 'work_items.bulk_progress', ids: [JOB_ID] });
    });
    expect(await within(drawer).findByText('Finished: 1 changed, 0 skipped.')).toBeDefined();
  });
});
