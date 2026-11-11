import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-045d S1: a change's tasks per stage, its child changes and releases, and closing with a
// description (REQ-CHG-088, -095, -096).

const CHG_ID = '01a1a2b3-0000-7000-8000-0000000c0005';
const CHILD_ID = '01a1a2b3-0000-7000-8000-0000000c0006';
const LINK_ID = '01a1a2b3-0000-7000-8000-0000000c0e06';

const change = {
  ...fakeIncident({
    id: CHG_ID,
    display_id: 'CHG-30',
    subject: 'Data centre move',
    status: 'review_in_review',
  }),
  type: 'change',
  stage: 'review',
  stage_path: 'default',
  version: 11,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

type Routes = NonNullable<Parameters<typeof consoleApi>[0]>['routes'];

function api(extra: Routes = {}) {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['technician'] },
      {
        permissions: ['changes.view', 'changes.edit'].map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      [`GET /api/v1/changes/${CHG_ID}`]: { body: change, headers: { ETag: '"11"' } },
      [`GET /api/v1/changes/${CHG_ID}/stages`]: {
        body: {
          stage: 'review',
          stage_path: 'default',
          status: 'review_in_review',
          version: 11,
          rail: [{ stage: 'review', state: 'current', optional: false, entries: [] }],
          moves: [
            {
              to_status: 'review_complete',
              to_stage: 'review',
              reason_mode: 'none',
              reason_list: null,
              required_fields: [],
              allowed: true,
              reason: null,
              missing: [],
              lands_in: 'closure_closed',
            },
          ],
        },
      },
      [`GET /api/v1/changes/${CHG_ID}/details`]: {
        body: { work_item_id: CHG_ID, version: 11, change_type: 'normal', change_reason: null },
      },
      [`GET /api/v1/changes/${CHG_ID}/approvals`]: { body: { items: [], people: {} } },
      [`GET /api/v1/changes/${CHG_ID}/tasks`]: {
        body: {
          items: [
            {
              id: 't1',
              work_item_id: CHG_ID,
              title: 'Label the racks',
              description: null,
              owner_id: null,
              group_id: null,
              status: 'open',
              priority: 'normal',
              due_at: null,
              done_at: null,
              done_by: null,
              stage: 'review',
              position: 0,
              from_plan: false,
              required: true,
              internal: false,
              version: 1,
              created_at: '2027-03-01T00:00:00Z',
              updated_at: '2027-03-01T00:00:00Z',
            },
          ],
          done: 0,
          total: 1,
        },
      },
      [`GET /api/v1/changes/${CHG_ID}/children`]: {
        body: [
          {
            link_id: LINK_ID,
            record_id: CHILD_ID,
            type: 'change',
            display_id: 'CHG-31',
            subject: 'Move the backup array',
            stage: 'implementation',
            status: 'implementation_in_progress',
            status_category: 'open',
          },
        ],
      },
      'GET /api/v1/changes/settings': {
        body: {
          statuses: [],
          closure_codes: [{ code: 'fixed', labels: null, disabled: false }],
          own_lists: {},
        },
      },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: a change’s tasks, children and closing (WP-045d S1)', () => {
  it('REQ-CHG-088: a task shows the stage it is for', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}?tab=tasks`);
    api();
    render(<App />);
    expect((await screen.findByTestId('inc-task-stage-0')).textContent).toBe('Review');
  });

  it('REQ-CHG-096: the children say closing waits; one is added by its number', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}?tab=children`);
    const fake = api({
      'GET /api/v1/changes/lookup/CHG-32': { body: { ...change, id: 'c32', display_id: 'CHG-32' } },
      [`POST /api/v1/changes/${CHG_ID}/children`]: { status: 201, body: { link_id: 'l2' } },
    });
    render(<App />);
    const panel = await screen.findByTestId('change-children');
    await waitFor(() => {
      expect(within(panel).getByTestId('change-child-CHG-31').textContent).toContain(
        'Move the backup array',
      );
    });
    expect(screen.getByTestId('change-children-open').textContent).toContain(
      '1 child is still open',
    );
    fireEvent.change(screen.getByTestId('change-child-number'), { target: { value: 'chg-32' } });
    fireEvent.click(screen.getByTestId('change-child-add'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/changes/${CHG_ID}/children`)).toHaveLength(1);
    });
    expect(fake.find('POST', `/api/v1/changes/${CHG_ID}/children`)[0]?.body).toEqual({
      child_id: 'c32',
    });
  });

  it('REQ-CHG-095: closing asks for the code and takes a description', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}`);
    const fake = api({
      [`POST /api/v1/changes/${CHG_ID}/moves`]: {
        body: { ...change, stage: 'closure', status: 'closure_closed', version: 12 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('move-review_complete'));
    const select = (await screen.findByTestId('move-closure-code')).querySelector(
      '.ant-select-selector',
    );
    if (select === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(select);
    fireEvent.click(await screen.findByTitle('Fixed'));
    fireEvent.change(screen.getByTestId('move-closing-text'), {
      target: { value: 'Moved, checked and signed off.' },
    });
    fireEvent.click(screen.getByTestId('move-ok'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/changes/${CHG_ID}/moves`)).toHaveLength(1);
    });
    expect(fake.find('POST', `/api/v1/changes/${CHG_ID}/moves`)[0]?.body).toMatchObject({
      to_status: 'review_complete',
      closure_code: 'fixed',
      resolution: 'Moved, checked and signed off.',
    });
  });
});
