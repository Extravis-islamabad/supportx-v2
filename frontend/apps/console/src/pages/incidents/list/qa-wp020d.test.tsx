import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-020d QA fix round (~/Desktop/qa-wp020d/QA-REPORT.md): test names cite the bug.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ME = fakeSession().user.id;
const ITEM = fakeIncident();
const ROUTES = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  'GET /api/v1/incidents': {
    body: {
      items: [{ ...ITEM, deleted_at: null }],
      has_more: false,
      next_cursor: null,
      estimated_total: 1,
      people: ITEM.people,
    },
  },
  'GET /api/v1/incidents/views': {
    body: [
      { view: 'open', count: 1, capped: false },
      { view: 'followed_by_me', count: 0, capped: false },
    ],
  },
  'GET /api/v1/incidents/counters': { body: [] },
  'GET /api/v1/incidents/list-fields': { body: [] },
  'GET /api/v1/incidents/saved-views': { body: [] },
  'GET /api/v1/incidents/view-filters': { body: [] },
  'GET /api/v1/incidents/list-settings/open': {
    body: { view_key: 'open', columns: [], sort: null, page_size: 50, version: null },
  },
};

beforeEach(() => {
  window.history.pushState({}, '', '/incidents');
});
afterEach(() => {
  restore();
  vi.useRealTimers();
  setDefaultClientFactory(inertClientFactory);
});

async function openList() {
  const realtime = scriptedRealtime();
  setDefaultClientFactory(realtime.factory);
  const fake = api({ routes: ROUTES });
  render(<App />);
  await screen.findByTestId(`inc-row-${ITEM.display_id}`);
  const counts = () => ({
    views: fake.find('GET', '/api/v1/incidents/views').length,
    counters: fake.find('GET', '/api/v1/incidents/counters').length,
  });
  await waitFor(() => {
    expect(counts().views).toBeGreaterThan(0);
  });
  return { realtime, counts };
}

describe('BUG-01: every view count follows the changes that move it', () => {
  // The person's own channel: follows, replies by others, a new direct report, a group joined.
  for (const type of [
    'work_items.lists_changed',
    'users.reports_changed',
    'access.changed',
  ] as const) {
    it(`BUG-01: "${type}" on my own channel recounts views and counters`, async () => {
      const { realtime, counts } = await openList();
      const before = counts();
      act(() => {
        realtime.publish(`:user:${ME}`, { type, ids: [] });
      });
      await waitFor(() => {
        expect(counts().views).toBeGreaterThan(before.views);
        expect(counts().counters).toBeGreaterThan(before.counters);
      });
    });
  }

  it('BUG-01: time-based counts (overdue, due today, created today) recount every minute', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { counts } = await openList();
    const before = counts();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    await waitFor(() => {
      expect(counts().views).toBeGreaterThan(before.views);
      expect(counts().counters).toBeGreaterThan(before.counters);
    });
  });
});

describe('BUG-02: the toolbar keeps its place when chips are added', () => {
  it('BUG-02: two toolbar rows that fit, and chips stack under a fixed-width search', async () => {
    await openList();
    // Row one: what to look at (the view and its buttons, the search); row two: how to narrow
    // and show it. Each is narrower than a desktop screen, so nothing wraps at random.
    const find = screen.getByTestId('inc-toolbar-find');
    const narrow = screen.getByTestId('inc-toolbar-narrow');
    for (const id of ['inc-view', 'inc-view-new', 'inc-search-group']) {
      expect(find.contains(screen.getByTestId(id)), id).toBe(true);
    }
    for (const id of ['inc-filter-priority', 'inc-sort', 'inc-page-size', 'inc-columns']) {
      expect(narrow.contains(screen.getByTestId(id)), id).toBe(true);
    }
    // The view selector and "New view" sit in the row itself, never in a box of their own that
    // a browser could size to the selector alone.
    expect(screen.getByTestId('inc-view-new').parentElement).toBe(find);
    // Chips go below the search box inside a column of fixed width: a chip adds height, never
    // width, so the controls after it do not jump to a new line.
    const search = screen.getByTestId('inc-search-group');
    expect(search.style.width).toBe('min(320px, 100%)');
    expect(search.classList.contains('ant-flex-vertical')).toBe(true);
  });
});
