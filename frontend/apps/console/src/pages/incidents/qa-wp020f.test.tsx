import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Incident } from '@supportx/api-client';
import {
  fakeConversationEntry,
  fakeCustomField,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// WP-020f QA fix round (~/Desktop/qa-wp020f/QA-REPORT.md): test names cite the bug.

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const REQUESTER = '01900000-0000-7000-8000-000000000201';

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const COMMON = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/organization/departments': { body: [] },
  'GET /api/v1/custom-fields': { body: [fakeCustomField()] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
  [`GET ${PATH}/conversation`]: { body: { items: [], people: {} } },
  [`GET ${PATH}/automation`]: { body: [] },
};

function record(item: Incident) {
  return { [`GET ${PATH}`]: { body: item, headers: { ETag: `"${String(item.version)}"` } } };
}

const entry = (overrides: Record<string, unknown>) => ({
  change_id: 'c-9',
  version: 9,
  kind: 'status',
  occurred_at: '2026-10-28T09:00:00Z',
  actor_type: 'user',
  actor_id: REQUESTER,
  actor_name: 'Yusra Requester',
  source: 'portal',
  reason: null,
  automation: null,
  changes: [],
  ...overrides,
});

beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  rememberTab(SESSION_USER, 'details');
});
afterEach(() => {
  restore();
});

describe('BUG-03: the requester acts as a person, not as automation', () => {
  it('BUG-03: a confirmation shows the why-line without the "Automatic" tag', async () => {
    rememberTab(SESSION_USER, 'history');
    api({
      routes: {
        ...COMMON,
        ...record(fakeIncident()),
        [`GET ${PATH}/history`]: {
          body: {
            items: [
              entry({
                changes: [
                  { field: 'status', old: 'resolved', new: 'closed' },
                  { field: 'requester_action', old: null, new: 'requester_confirmed' },
                ],
              }),
            ],
            next_cursor: null,
            people: {},
          },
        },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('inc-history-why')).textContent).toBe(
      'The requester confirmed the fix, so it was closed.',
    );
    expect(screen.queryByTestId('inc-history-automatic')).toBeNull();
    const text = screen.getByTestId('inc-history').textContent;
    expect(text).toContain('Yusra Requester');
    expect(text).toContain('in the portal');
    // The why-line says it; no raw row or code repeats it.
    expect(text).not.toContain('requester_');
    expect(within(screen.getByTestId('inc-history-entry')).getAllByRole('listitem')).toHaveLength(
      1,
    );
  });
});

describe('BUG-01: the requester’s own words are received, not unsent', () => {
  it('BUG-01: a received reply says so and has no "Not sent" warning', async () => {
    rememberTab(SESSION_USER, 'conversation');
    api({
      routes: {
        ...COMMON,
        ...record(fakeIncident()),
        [`GET ${PATH}/conversation`]: {
          body: {
            items: [
              fakeConversationEntry({
                kind: 'reply',
                visibility: 'public',
                body: '<p>Still broken for me.</p>',
                delivery_state: 'received',
                created_by: REQUESTER,
              }),
            ],
            people: { [REQUESTER]: { display_name: 'Yusra Requester', email: 'y@example.com' } },
          },
        },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('conv-received')).textContent).toBe('Received');
    expect(screen.queryByTestId('conv-not-sent')).toBeNull();
  });
});

describe('BUG-04: technicians cannot choose "Confirmed by requester"', () => {
  it('BUG-04: the Close dialog shows the code as unavailable and says why', async () => {
    const base = fakeIncident({ status: 'resolved', status_category: 'resolved', version: 5 });
    api({
      routes: {
        ...COMMON,
        ...record({
          ...base,
          actions: base.actions.map((a) =>
            a.action === 'close' ? { ...a, allowed: true, reason: null, missing: [] } : a,
          ),
        }),
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-action-close'));
    const select = await screen.findByTestId('inc-closure-code');
    const selector = select.querySelector('.ant-select-selector');
    if (selector === null) throw new Error('not an Ant Design Select');
    fireEvent.mouseDown(selector);
    const option = await screen.findByTitle(
      'Confirmed by requester: set only when the requester confirms the fix',
    );
    expect(option.classList.contains('ant-select-item-option-disabled')).toBe(true);
    expect(screen.getByTitle('Fixed').classList.contains('ant-select-item-option-disabled')).toBe(
      false,
    );
  });
});
