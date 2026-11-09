import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-044c D14 (REQ-PRB-071): incident technicians see the causing problem narrowly.

const ITEM = fakeIncident();
const PATH = `/api/v1/incidents/${ITEM.id}`;
const CAUSE = {
  id: '01a1a2b3-0000-7000-8000-00000000e001',
  display_id: 'PRB-7',
  subject: 'Mail relay drops messages',
  status: 'investigation',
  known_error: true,
  workaround: '<p>Restart the mail relay.</p>',
  target_at: '2026-12-01T09:00:00Z',
  may_open: false,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function open(cause: unknown) {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
      'GET /api/v1/incidents/categories': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/organization/sites': { body: [] },
      [`GET ${PATH}`]: { body: ITEM, headers: { ETag: '"1"' } },
      [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
      [`GET ${PATH}/causing-problem`]: { body: cause },
    },
  });
  restore = fake.restore;
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  render(<App />);
}

describe('the causing problem on an incident (WP-044c D14)', () => {
  it('REQ-PRB-071: its ID, status, known error marker, workaround and target, never a link without access', async () => {
    open(CAUSE);
    const card = await screen.findByTestId('inc-causing-problem');
    expect(card.textContent).toContain('PRB-7');
    expect(card.textContent).toContain('Mail relay drops messages');
    expect(card.textContent).toContain('Restart the mail relay.');
    expect(within(card).getByTestId('inc-causing-known-error')).toBeDefined();
    expect(within(card).getByTestId('inc-causing-target')).toBeDefined();
    expect(within(card).queryByTestId('inc-causing-problem-open')).toBeNull();
  });

  it('REQ-PRB-071: who may see problems gets a link to it', async () => {
    open({ ...CAUSE, may_open: true });
    const link = await screen.findByTestId('inc-causing-problem-open');
    expect(link.getAttribute('href')).toBe(`/problems/${CAUSE.id}`);
  });

  it('REQ-PRB-071: no cause, no card', async () => {
    open(null);
    await screen.findByTestId('inc-heading');
    expect(screen.queryByTestId('inc-causing-problem')).toBeNull();
  });
});
