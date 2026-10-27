import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeIncidentTemplate } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// REQ-INC-019, REQ-SEC-029 AC2 (WP-039 session 3): a new incident's input survives a session
// timeout in the same tab and comes back after signing in again.

let restore: () => void = () => undefined;
const ROUTES = {
  'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
  'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
  'GET /api/v1/incidents/categories': { body: [] },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
};
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

beforeEach(() => {
  window.history.pushState({}, '', '/incidents/new');
});
afterEach(() => {
  restore();
  window.sessionStorage.clear();
});

describe('New incident: kept input', () => {
  it('"start empty" forgets the restored input', async () => {
    window.sessionStorage.setItem(
      `supportx.draft.${ADMIN.tenant.id}.${ADMIN.user.id}.incident-new`,
      JSON.stringify({ subject: 'Old draft' }),
    );
    restore = consoleApi({ me: ADMIN, routes: ROUTES }).restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('inc-draft-start-empty'));
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>('inc-subject').value).toBe('');
    });
    expect(screen.queryByTestId('inc-draft-restored')).toBeNull();
  });

  it('what was typed before a timeout is back, and the person is told', async () => {
    window.sessionStorage.setItem(
      `supportx.draft.${ADMIN.tenant.id}.${ADMIN.user.id}.incident-new`,
      JSON.stringify({ subject: 'Printer on fire', description: '<p>Second floor</p>' }),
    );
    const fake = consoleApi({
      me: ADMIN,
      routes: ROUTES,
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('inc-draft-restored')).toBeDefined();
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>('inc-subject').value).toBe('Printer on fire');
    });
  });
});
