import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// QA6 (2026-11-06) incident minors, each test named after its bug.

const SESSION_USER = '01900000-0000-7000-8000-000000000101'; // the fake session's user
const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function open(state: unknown) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
      [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
    },
  });
  restore = fake.restore;
  // React Router keeps navigation state under `usr` in the history entry.
  window.history.pushState({ usr: state, key: 'qa6', idx: 0 }, '', `/incidents/${ITEM.id}`);
  render(<App />);
}

const selected = (name: RegExp) =>
  screen.getByRole('tab', { name }).getAttribute('aria-selected') === 'true';

describe('QA6 incident minors', () => {
  it('QA6-INC-04: a record just made opens on Conversation, not the tab used last', async () => {
    rememberTab(SESSION_USER, 'automation');
    open({ justMade: true });
    await screen.findByTestId('inc-heading');
    await waitFor(() => {
      expect(selected(/^Conversation/)).toBe(true);
    });
  });

  it('QA6-INC-04: opening a record otherwise keeps the tab used last (D-081)', async () => {
    rememberTab(SESSION_USER, 'details');
    open(null);
    await screen.findByTestId('inc-heading');
    await waitFor(() => {
      expect(selected(/^Details/)).toBe(true);
    });
  });
});
