import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  problem,
} from '@supportx/api-client/testing';

import { App } from '../../App';
import { clickAction } from '../../test/actions';
import { consoleApi, fakeSession } from '../../test/api';
import { rememberTab } from './tabs';

// WP-046b S4 (REQ-INC-129; lane C): one Idempotency-Key per dialog opening, a new one after a
// real refusal, and the actor told in words when the announcement stays a draft.

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ITEM = fakeIncident({ subject: 'Mail relay down' });
const PATH = `/api/v1/incidents/${ITEM.id}`;

let restore: () => void = () => undefined;
beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  rememberTab(ADMIN.user.id, 'details');
});
afterEach(() => {
  restore();
});

describe('Announce from an incident', () => {
  it('a refused try gets a new key; the draft is said in words', async () => {
    let tries = 0;
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
        'GET /api/v1/incidents/categories': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/custom-fields': { body: [] },
        'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
        [`GET ${PATH}`]: { body: ITEM },
        [`GET ${PATH}/conversation`]: { body: { items: [], people: {} } },
        [`GET ${PATH}/announcements`]: { body: [] },
        [`POST ${PATH}/announcements`]: () => {
          tries += 1;
          return tries === 1
            ? { status: 422, body: problem(422, 'validation_failed') }
            : {
                status: 201,
                body: { id: 'a-1', display_id: 'ANN-4', title: 'Mail relay down', status: 'draft' },
              };
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    await clickAction('inc-op-announce');
    // Starts from the subject only; the display ID in the text, nothing else of the incident.
    const title = await screen.findByTestId('inc-announce-title');
    expect((title as HTMLInputElement).value).toBe('Mail relay down');
    fireEvent.click(screen.getByTestId('inc-announce-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/announcements`)).toHaveLength(1);
    });
    fireEvent.click(screen.getByTestId('inc-announce-confirm'));
    await waitFor(() => {
      expect(fake.find('POST', `${PATH}/announcements`)).toHaveLength(2);
    });
    const [first, second] = fake.find('POST', `${PATH}/announcements`);
    const firstKey = first?.headers.get('Idempotency-Key');
    expect(firstKey).toBeTruthy();
    expect(second?.headers.get('Idempotency-Key')).not.toBe(firstKey);
    expect(await screen.findByText(/Saved as draft ANN-4/)).toBeTruthy();
  });
});
