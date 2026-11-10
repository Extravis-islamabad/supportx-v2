import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeIncidentCatalogue, fakeSession } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, problem } from '../../../test/api';

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

function api(extra: NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']> = {}) {
  const fake = consoleApi({
    me: fakeSession({ roles: ['tenant_admin'] }),
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
      ...extra,
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
    // One save bar (template E): a switch changes the draft; Save sends it.
    expect(fake.find('PATCH', '/api/v1/portal/settings')).toHaveLength(0);
    expect((await screen.findByTestId('portal-settings-save-bar')).textContent).toContain(
      '1 unsaved change',
    );
    fireEvent.click(screen.getByTestId('settings-save'));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/portal/settings')).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', '/api/v1/portal/settings');
    expect(sent?.body).toEqual({ profile_editing: false });
    expect(sent?.headers.get('If-Match')).toBe('"4"');
  });

  it('a save refused after another owner took its part says so above the bar', async () => {
    window.history.pushState({}, '', '/admin/portal');
    const fake = api({
      'PATCH /api/v1/catalog/settings': {
        body: { hide_default_incident_template: true, version: 3 },
      },
      'PATCH /api/v1/portal/settings': {
        status: 422,
        body: problem(422, 'validation_failed'),
      },
    });
    render(<App />);
    await screen.findByTestId('portal-settings');
    fireEvent.click(within(screen.getByTestId('ps-hide-default-form')).getByRole('switch'));
    fireEvent.click(within(screen.getByTestId('ps-profile-editing')).getByRole('switch'));
    fireEvent.click(screen.getByTestId('settings-save'));
    expect(await screen.findByTestId('portal-settings-partly')).toBeDefined();
    expect(fake.find('PATCH', '/api/v1/catalog/settings')).toHaveLength(1);
    // The refusal is shown on the page (not a toast), and the portal's change is still to save.
    expect(screen.getByRole('alert')).toBeDefined();
    expect(screen.getByTestId('portal-settings-save-bar').textContent).toContain(
      '1 unsaved change',
    );
    fireEvent.click(screen.getByTestId('settings-discard'));
    await waitFor(() => {
      expect(screen.queryByTestId('portal-settings-partly')).toBeNull();
    });
  });

  it('a save someone else beat opens the conflict dialog; Reload shows the latest', async () => {
    window.history.pushState({}, '', '/admin/portal');
    const fake = api({
      'PATCH /api/v1/portal/settings': {
        status: 409,
        body: problem(409, 'version_conflict'),
      },
    });
    render(<App />);
    await screen.findByTestId('portal-settings');
    fireEvent.click(within(screen.getByTestId('ps-profile-editing')).getByRole('switch'));
    fireEvent.click(screen.getByTestId('settings-save'));
    const reload = await screen.findByTestId('conflict-reload');
    expect(screen.queryByTestId('portal-settings-partly')).toBeNull(); // nothing saved before it
    const before = fake.find('GET', '/api/v1/portal/settings').length;
    fireEvent.click(reload);
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/portal/settings').length).toBeGreaterThan(before);
    });
    // My edit is dropped: nothing left to save, so the bar goes.
    await waitFor(() => {
      expect(screen.queryByTestId('settings-save')).toBeNull();
    });
  });
});
