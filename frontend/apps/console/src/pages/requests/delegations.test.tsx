import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// WP-047a S3b (REQ-SR-035): the Delegations page lists yours and follows them live.

const ME = fakeSession({ roles: ['technician'] });
const DELEGATE = '01a1a2b3-0000-7000-8000-00000000d035';
const ROW = {
  id: '01a1a2b3-0000-7000-8000-00000000d135',
  delegator_id: ME.user.id,
  delegate_id: DELEGATE,
  starts_at: '2026-11-20T00:00:00Z',
  ends_at: '2099-11-27T00:00:00Z',
  ended_at: null,
  reason: 'Leave',
  version: 1,
  created_at: '2026-11-20T00:00:00Z',
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

describe('console: approval delegations', () => {
  it('a delegation set by someone else shows without a refresh', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/approvals/delegations');
    let rows: unknown[] = [];
    const fake = consoleApi({
      me: ME,
      routes: {
        'GET /api/v1/approval-delegations': () => ({ body: { items: rows } }),
        [`GET /api/v1/users/${DELEGATE}`]: {
          body: { id: DELEGATE, display_name: 'Dana Delegate', email: 'dana@example.com' },
        },
        [`GET /api/v1/users/${ME.user.id}`]: {
          body: { id: ME.user.id, display_name: 'Me', email: 'me@example.com' },
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByText('No delegations.')).toBeTruthy();
    rows = [ROW];
    act(() => {
      realtime.publish(`:user:${ME.user.id}`, {
        type: 'work_items.delegations_changed',
        ids: [ROW.id],
      });
    });
    expect((await screen.findByTestId('delegation-state')).textContent).toBe('Active');
  });
});
