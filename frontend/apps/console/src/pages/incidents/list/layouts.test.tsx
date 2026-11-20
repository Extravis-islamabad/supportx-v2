import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-046b S3b (REQ-INC-111, REQ-INC-112): the list as cards, a board and a calendar, with lane
// C's conditions (the plan's review, 2026-11-20).

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ITEM = { ...fakeIncident(), deleted_at: null };
const LIST = { items: [ITEM], has_more: false, next_cursor: null, people: ITEM.people };
const FIELDS = [
  { name: 'subject', type: 'string', values: [], multiple: false, sortable: true, dimension: null },
  { name: 'status', type: 'enum', values: [], multiple: false, sortable: true, dimension: null },
  // No priority among the list's fields: this reader's role hides it (ADR-047).
  {
    name: 'resolution_due_at',
    type: 'datetime',
    values: [],
    multiple: false,
    sortable: true,
    dimension: null,
  },
];

function routes(layout: string | null, extra: Record<string, unknown> = {}) {
  return {
    'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
    'GET /api/v1/incidents/categories': { body: [] },
    'GET /api/v1/organization/groups': { body: [] },
    'GET /api/v1/organization/sites': { body: [] },
    'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
    'GET /api/v1/incidents': { body: LIST },
    'GET /api/v1/incidents/views': { body: [{ view: 'open', count: 1, capped: false }] },
    'GET /api/v1/incidents/list-fields': { body: FIELDS },
    'GET /api/v1/incidents/saved-views': { body: [] },
    'GET /api/v1/incidents/view-filters': {
      body: [{ view: 'open', expressible: true, filter: null }],
    },
    'GET /api/v1/incidents/list-settings/open': {
      body: {
        view_key: 'open',
        columns: [],
        sort: null,
        page_size: 50,
        row_colour_by: 'priority',
        layout,
        group_by: null,
        version: layout === null ? null : 3,
      },
      headers: layout === null ? {} : { ETag: '"3"' },
    },
    'PUT /api/v1/incidents/list-settings/open': (call: { body: unknown }) => ({
      body: { view_key: 'open', version: 4, ...(call.body as object) },
      headers: { ETag: '"4"' },
    }),
    // Each board column asks with its own condition: the card is only in its own status's.
    'POST /api/v1/incidents/list': (call: { body: unknown }) => {
      const text = JSON.stringify(call.body);
      return text.includes('"field":"status"') && !text.includes(`"value":"${ITEM.status}"`)
        ? { body: { ...LIST, items: [] } }
        : { body: LIST };
    },
    'POST /api/v1/incidents/board': {
      body: [
        { key: ITEM.status, count: 30 },
        { key: 'resolved', count: 0 },
      ],
    },
    [`GET /api/v1/incidents/${ITEM.id}`]: {
      body: ITEM,
      headers: { ETag: `"${String(ITEM.version)}"` },
    },
    ...extra,
  } as Parameters<typeof consoleApi>[0] extends infer A
    ? A extends { routes?: infer R }
      ? R
      : never
    : never;
}

describe('Incident list layouts (WP-046b S3b)', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/incidents');
  });
  afterEach(() => {
    restore();
  });

  it('the switch saves the layout and keeps the row colouring (no other choice is lost)', async () => {
    const fake = api({ routes: routes(null) });
    render(<App />);
    const switcher = await screen.findByTestId('inc-layout');
    // Usable once the person's setting is read (a save before would replace it).
    await waitFor(() => {
      expect(switcher.querySelector('.ant-segmented-disabled')).toBeNull();
    });
    fireEvent.click(within(switcher).getByText('Cards'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/incidents/list-settings/open')).toHaveLength(1);
    });
    const saved = fake.find('PUT', '/api/v1/incidents/list-settings/open')[0]?.body as Record<
      string,
      unknown
    >;
    expect(saved.layout).toBe('cards');
    expect(saved.row_colour_by).toBe('priority');
  });

  it('REQ-INC-111: cards carry the unread cue and show no field the reader cannot see', async () => {
    api({ routes: routes('cards') });
    render(<App />);
    const card = await screen.findByTestId(`inc-card-${ITEM.display_id}`);
    expect(within(card).getByText(ITEM.subject, { exact: false })).toBeTruthy();
    // Priority is not among this reader's list fields: never on a card.
    expect(within(card).queryByText('Priority:')).toBeNull();
    fireEvent.click(within(screen.getByTestId('inc-cards-density')).getByText('Compact'));
    expect(screen.queryByText('Status:')).toBeNull(); // compact: values only, names for AT
  });

  it("the board counts by the server, and each column asks the list with the column's condition", async () => {
    const fake = api({ routes: routes('board') });
    render(<App />);
    await screen.findByTestId('inc-board');
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/incidents/board')).toHaveLength(1);
    });
    await waitFor(() => {
      const bodies = fake.find('POST', '/api/v1/incidents/list').map((c) => JSON.stringify(c.body));
      expect(bodies.some((b) => b.includes(`"value":"${ITEM.status}"`))).toBe(true);
    });
    // 1 shown of 30 in all, in words; an empty status still has its column.
    expect((await screen.findByTestId(`inc-board-stage-count-${ITEM.status}`)).textContent).toBe(
      '1 of 30',
    );
    expect(screen.getByTestId('inc-board-stage-column-resolved')).toBeTruthy();
  });

  it('a status move with no step to the column says why and runs nothing', async () => {
    const fake = api({ routes: routes('board') });
    render(<App />);
    const opener = await screen.findByTestId(`inc-board-stage-move-${ITEM.id}`);
    fireEvent.click(opener);
    const menu = (await screen.findAllByRole('menu')).at(-1);
    if (menu === undefined) throw new Error('no menu');
    fireEvent.click(within(menu).getByText('Resolved', { exact: false }));
    await waitFor(() => {
      expect(screen.getByTestId('inc-board-stage-refusal').textContent).not.toBe('');
    });
    expect(
      fake.find('POST', `/api/v1/incidents/${ITEM.id}/actions/resolve`).length +
        fake.find('POST', `/api/v1/incidents/${ITEM.id}/actions`).length,
    ).toBe(0);
  });

  it('REQ-INC-112: the calendar asks by POST for the range and counts those with no due time', async () => {
    const fake = api({
      routes: routes('calendar', {
        'POST /api/v1/incidents/list': (call: { body: unknown }) => {
          const text = JSON.stringify((call.body as { filter?: unknown }).filter);
          return text.includes('is_null')
            ? { body: { ...LIST, items: [], estimated_total: 3 } }
            : { body: LIST };
        },
      }),
    });
    render(<App />);
    await screen.findByTestId('inc-calendar');
    await waitFor(() => {
      const filters = fake
        .find('POST', '/api/v1/incidents/list')
        .map((c) => JSON.stringify(c.body));
      expect(filters.some((f) => f.includes('"op":"gte"') && f.includes('"op":"lt"'))).toBe(true);
    });
    expect((await screen.findByTestId('inc-cal-no-due')).textContent).toContain('3');
    // Nothing of the filter went into a URL.
    expect(fake.find('GET', '/api/v1/incidents')).toHaveLength(0);
  });
});
