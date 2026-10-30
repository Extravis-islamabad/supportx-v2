import { act, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// REQ-WI-012: a live update must not dim a list someone is reading. The spinner belongs to a first
// load (or a filter, view or page the user changed); a background refetch keeps the rows as they are.

let restore: () => void = () => undefined;
const ITEM = fakeIncident();
const PAGE = {
  body: {
    items: [{ ...ITEM, deleted_at: null }],
    has_more: false,
    next_cursor: null,
    estimated_total: 1,
    people: ITEM.people,
  },
};
const CHANNEL = 't:demo:queue:incidents';

function routes(list: unknown) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [CHANNEL] } },
    'GET /api/v1/incidents': list,
    'GET /api/v1/incidents/views': { body: [{ view: 'open', count: 1, capped: false }] },
    'GET /api/v1/incidents/counters': { body: [] },
    'GET /api/v1/incidents/list-fields': { body: [] },
    'GET /api/v1/incidents/saved-views': { body: [] },
    'GET /api/v1/incidents/view-filters': { body: [] },
    'GET /api/v1/incidents/list-settings/open': {
      body: { view_key: 'open', columns: [], sort: null, page_size: 50, version: null },
    },
  } as NonNullable<Parameters<typeof consoleApi>[0]>['routes'];
}

/** Answers held until `release()`, so a test can look at the screen while one is on its way. */
function heldAnswers() {
  const waiting: (() => void)[] = [];
  return {
    route: async () => {
      await new Promise<void>((resolve) => {
        waiting.push(resolve);
      });
      return PAGE;
    },
    release: () => {
      for (const resolve of waiting.splice(0)) resolve();
    },
  };
}

const spinner = () => document.querySelector('.ant-table-wrapper .ant-spin-spinning');
const dimmed = () => document.querySelector('.ant-table-wrapper .ant-spin-blur');

beforeEach(() => {
  window.history.pushState({}, '', '/incidents');
});
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

describe('REQ-WI-012: the incident list while it refetches', () => {
  it('a first load shows the spinner', async () => {
    const held = heldAnswers();
    const fake = consoleApi({ routes: routes(held.route) });
    restore = fake.restore;
    render(<App />);
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/incidents')).toHaveLength(1);
    });
    await waitFor(() => {
      expect(spinner()).not.toBeNull();
    });
    await act(async () => {
      held.release();
      await Promise.resolve();
    });
    await screen.findByTestId(`inc-row-${ITEM.display_id}`);
    await waitFor(() => {
      expect(spinner()).toBeNull();
    });
  });

  it('a live update refetches with no spinner, and the rows stay', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    const held = heldAnswers();
    let first = true;
    const fake = consoleApi({
      routes: routes(() => {
        if (first) {
          first = false;
          return PAGE;
        }
        return held.route();
      }),
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId(`inc-row-${ITEM.display_id}`);
    await waitFor(() => {
      expect(realtime.channels()).toContain(CHANNEL);
    });
    act(() => {
      realtime.publish(':queue:incidents', { type: 'work_items.changed', ids: [ITEM.id] });
    });
    // The refetch is on its way and not answered yet: this is the moment a dim would show.
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/incidents')).toHaveLength(2);
    });
    expect(spinner()).toBeNull();
    expect(dimmed()).toBeNull();
    const table = screen.getByTestId('inc-table');
    expect(within(table).getByTestId(`inc-row-${ITEM.display_id}`)).toBeDefined();
    await act(async () => {
      held.release();
      await Promise.resolve();
    });
  });
});
