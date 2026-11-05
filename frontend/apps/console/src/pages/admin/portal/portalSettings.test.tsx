import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-032 D8 (REQ-PRT-031): every portal setting on one page, each saved where it lives.

const SETTINGS = {
  search_sources: ['items', 'articles', 'announcements', 'requests'],
  profile_editing: true,
  requester_reminders: true,
  version: 4,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api() {
  const fake = consoleApi({
    routes: {
      'GET /api/v1/portal/settings': { body: SETTINGS },
      'PATCH /api/v1/portal/settings': {
        body: { ...SETTINGS, profile_editing: false, version: 5 },
      },
      'GET /api/v1/service-requests/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/catalog/settings': {
        body: { hide_default_incident_template: false, version: 2 },
      },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('console: portal settings', () => {
  it('groups every setting with a one-line explanation, and saves one with If-Match', async () => {
    window.history.pushState({}, '', '/admin/portal');
    const fake = api();
    render(<App />);
    expect(await screen.findByTestId('portal-settings')).toBeDefined();
    for (const id of [
      'ps-hide-default-form',
      'ps-due-requests',
      'ps-on-behalf',
      'ps-approvals-hidden',
    ]) {
      expect(screen.getByTestId(id)).toBeDefined();
    }
    expect(screen.getByTestId('ps-later-guest_requests')).toBeDefined(); // shown as later
    fireEvent.click(within(screen.getByTestId('ps-profile-editing')).getByRole('switch'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/portal/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/portal/settings');
    expect(sent?.body).toEqual({ profile_editing: false });
    expect(sent?.headers.get('If-Match')).toBe('"4"');
  });
});
