import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';
import { rememberTab } from './tabs';

// ADR-047 slice c: a field the person's roles withhold says so; a read-only one has no editor.

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const ITEM = {
  ...fakeIncident({ urgency: 'high' }),
  impact_details: null,
  hidden_fields: ['impact_details'],
  masked_fields: [],
  read_only_fields: ['impact_details', 'urgency'],
};
const PATH = `/api/v1/incidents/${ITEM.id}`;

let restore: () => void = () => undefined;

describe('Field access on an incident', () => {
  beforeEach(() => {
    window.history.pushState({}, '', `/incidents/${ITEM.id}`);
    rememberTab(SESSION_USER, 'details');
  });
  afterEach(() => {
    restore();
  });

  it('a hidden field shows its row as "Not shown to you"; a read-only one cannot be edited', async () => {
    const fake = consoleApi({
      routes: {
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
        'GET /api/v1/incidents/categories': { body: [] },
        'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
        [`GET ${PATH}`]: { body: ITEM },
        [`GET ${PATH}/history`]: { body: { items: [], next_cursor: null, people: {} } },
      },
    });
    restore = fake.restore;
    render(<App />);
    const properties = await screen.findByTestId('inc-properties');
    expect(within(properties).getByText('Impact details')).toBeDefined();
    expect(within(properties).getByTestId('restricted-hidden').textContent).toBe(
      'Not shown to you',
    );
    expect(within(properties).queryByRole('button', { name: 'Edit Impact details' })).toBeNull();
    expect(within(properties).queryByRole('button', { name: 'Edit Urgency' })).toBeNull();
    expect(within(properties).getByRole('button', { name: 'Edit Requester' })).toBeDefined();
  });
});
