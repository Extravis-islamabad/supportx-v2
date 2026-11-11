import { act, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-045d S2: the CAB pack (REQ-CHG-102). One printable page with the summary, the risk and
// its score, the plans, the schedule, the downtime and the approvals, in the reader's language.

const CHG_ID = '01a1a2b3-0000-7000-8000-0000000c0a01';

const change = {
  ...fakeIncident({
    id: CHG_ID,
    display_id: 'CHG-40',
    subject: 'Core router swap',
    status: 'cab_awaiting',
  }),
  type: 'change',
  stage: 'cab_review',
  stage_path: 'default',
  version: 9,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

function api(locale: 'en' | 'ar' = 'en') {
  const fake = consoleApi({
    me: fakeSession(
      { roles: ['technician'], locale },
      {
        permissions: ['changes.view'].map((key) => ({
          key,
          scope: 'all' as const,
          scopes: ['all' as const],
          conditional: false,
        })),
      },
    ),
    routes: {
      [`GET /api/v1/changes/${CHG_ID}`]: { body: change, headers: { ETag: '"9"' } },
      [`GET /api/v1/changes/${CHG_ID}/details`]: {
        body: {
          work_item_id: CHG_ID,
          version: 3,
          change_type: 'normal',
          change_reason: null,
          risk: 'high',
          risk_score: 14,
          risk_chosen: null,
          risk_reason: null,
          sent_back: false,
        },
      },
      [`GET /api/v1/changes/${CHG_ID}/plan`]: {
        body: [
          { section: 'backout', content: '<p>Swap the old router back in.</p>', version: 1 },
          { section: 'impact', content: null, version: 0 },
        ],
      },
      [`GET /api/v1/changes/${CHG_ID}/schedule`]: {
        body: [
          {
            stage: 'implementation',
            scheduled_start: '2027-03-01T22:00:00Z',
            scheduled_end: '2027-03-01T23:00:00Z',
            actual_start: null,
            actual_end: null,
            outcome: null,
            version: 1,
          },
        ],
      },
      [`GET /api/v1/changes/${CHG_ID}/downtimes`]: { body: [] },
      [`GET /api/v1/changes/${CHG_ID}/conflicts`]: {
        body: {
          items: [
            {
              kind: 'freeze',
              blocks: true,
              starts_at: '2027-03-01T20:00:00Z',
              ends_at: '2027-03-02T06:00:00Z',
              window_id: 'w1',
              window_name: 'Month-end freeze',
              window_labels: null,
              record_id: null,
            },
          ],
          passed_window_ids: [],
        },
      },
      [`GET /api/v1/changes/${CHG_ID}/approvals`]: { body: { items: [], people: {} } },
      'GET /api/v1/changes/settings': {
        body: {
          statuses: [],
          closure_codes: [],
          own_lists: { change_type: [{ code: 'normal', labels: null, disabled: false }] },
        },
      },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: the CAB pack (REQ-CHG-102)', () => {
  it('AC1: the pack holds the risk score and the backout plan, ready to print', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}/pack`);
    api();
    render(<App />);
    const pack = await screen.findByTestId('change-pack');
    expect(within(pack).getByText(/CHG-40/)).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId('pack-risk-score').textContent).toContain('14');
    });
    expect(screen.getByTestId('pack-risk-level').textContent).toContain('High');
    expect((await screen.findByTestId('pack-plan-backout')).textContent).toContain(
      'Swap the old router back in.',
    );
    expect(screen.queryByTestId('pack-plan-impact')).toBeNull();
    // AC1: the conflict list, each with what it is.
    const conflicts = await screen.findByTestId('pack-conflicts');
    expect((await within(conflicts).findByTestId('conflict-freeze')).textContent).toContain(
      'Month-end freeze',
    );
    expect(screen.getByTestId('pack-print').textContent).toBe('Print or save as PDF');
    // The print button is left out of the printed page by the app's print rules.
    expect(screen.getByTestId('pack-print').closest('[data-sx-no-print]')).not.toBeNull();
  });

  it('AC2: in Arabic the pack reads right to left, in Arabic labels', async () => {
    window.history.pushState({}, '', `/changes/${CHG_ID}/pack`);
    api('ar');
    render(<App />);
    await screen.findByTestId('change-pack');
    await waitFor(() => {
      expect(document.documentElement.getAttribute('dir')).toBe('rtl');
    });
    expect(screen.getByTestId('pack-summary').textContent).toContain('الملخص');
    expect(screen.getByTestId('pack-print').textContent).toBe('طباعة أو حفظ بصيغة PDF');
  });

  it('lane C: the pack follows the change live, with no refresh', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', `/changes/${CHG_ID}/pack`);
    const fake = api();
    render(<App />);
    await screen.findByTestId('pack-risk-score');
    const before = fake.find('GET', `/api/v1/changes/${CHG_ID}/plan`).length;
    act(() => {
      realtime.publish(`:wi:${CHG_ID}`, { type: 'work_items.changed', ids: [CHG_ID] });
    });
    await waitFor(() => {
      expect(fake.find('GET', `/api/v1/changes/${CHG_ID}/plan`).length).toBeGreaterThan(before);
    });
  });
});
