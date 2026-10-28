import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BrandingSettings, IdentitySettings, Incident } from '@supportx/api-client';
import {
  fakeBranding,
  fakeIncident,
  fakeIncidentCatalogue,
  fakeIncidentTemplate,
  fakeSession,
  problem,
} from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';

import { App } from './App';
import { consoleApi } from './test/api';

// QA WP-029 BUG-05: one shared conflict dialog in every editor. A stale save names who saved
// first, when, and which fields; records without field history (the server sends no fields)
// are compared by the dialog itself: the version the editor opened against the one saved now.

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

/** The 409 of a record without field history: who and when, no fields. */
function stale(current: number) {
  return {
    status: 409,
    body: problem(409, 'version_conflict', {
      params: {
        expected_version: current - 1,
        current_version: current,
        changed_by: 'Bilal Admin',
        changed_at: '2026-10-28T09:30:00Z',
        changed_fields: '',
      },
    }),
  };
}

/** The dialog names Bilal and the one field that differs, in words. */
async function expectNamed(field: string) {
  const who = await screen.findByTestId('conflict-who');
  expect(who.textContent).toContain('Bilal Admin saved it at');
  await waitFor(() => {
    expect(who.textContent).toContain(`Changed: ${field}.`);
  });
}

function open(path: string) {
  window.history.pushState({}, '', path);
  render(<App />);
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
  vi.restoreAllMocks();
});

describe('QA WP-029 BUG-05: the shared conflict dialog', () => {
  it('BUG-05: a sign-in security card names who saved first and which setting changed', async () => {
    const settings: IdentitySettings = {
      console_idle_seconds: 3600,
      console_absolute_seconds: 43200,
      portal_idle_seconds: 1800,
      portal_absolute_seconds: 43200,
      create_people_on_sign_in: true,
      invitation_valid_days: 7,
      password_min_length: 12,
      password_upper: true,
      password_lower: true,
      password_digits: true,
      password_special: true,
      password_history: 5,
      password_expiry_days: 0,
      password_breached_check: true,
      mfa_grace_days: 7,
      password_policy_editable: true,
      password_policy_state: 'applied',
      password_policy_error: null,
      version: 1,
    };
    let saved = false;
    const fake = api({
      me: ADMIN,
      routes: {
        // After the other save: their version, with a longer minimum length.
        'GET /api/v1/identity/settings': () => ({
          body: saved ? { ...settings, password_min_length: 14, version: 2 } : settings,
        }),
        'GET /api/v1/identity/sso': { body: { items: [] } },
        'GET /api/v1/identity/invitations': { body: { items: [] } },
        'GET /api/v1/identity/mfa': { body: { roles: [] } },
        'PUT /api/v1/identity/settings': () => {
          if (saved) return { body: { ...settings, password_history: 8, version: 3 } };
          saved = true;
          return stale(2);
        },
      },
    });
    open('/admin/security');
    fireEvent.change(await screen.findByTestId('security-password_history'), {
      target: { value: '8' },
    });
    fireEvent.click(screen.getByTestId('security-password-save'));
    await expectNamed('Minimum length');
    // Keep mine: my change saved again on their version.
    fireEvent.click(screen.getByTestId('conflict-keep-mine'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/settings')).toHaveLength(2);
    });
    expect(fake.find('PUT', '/api/v1/identity/settings')[1]?.headers.get('If-Match')).toBe('"2"');
  });

  it('BUG-05: an incident settings card (shared save) names the setting changed', async () => {
    const catalogue = fakeIncidentCatalogue();
    let saved = false;
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/incidents/settings': () => ({
          body: saved
            ? { ...catalogue, keep_following_on_handover: false, version: catalogue.version + 1 }
            : catalogue,
        }),
        'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
        'GET /api/v1/incidents/categories': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'GET /api/v1/organization/sites': { body: [] },
        'PATCH /api/v1/incidents/settings': () => {
          saved = true;
          return stale(catalogue.version + 1);
        },
      },
    });
    open('/admin/incidents/general');
    fireEvent.change(await screen.findByTestId('settings-prefix'), { target: { value: 'QAT' } });
    fireEvent.click(screen.getByTestId('settings-numbering-save'));
    await expectNamed('Keep following an incident after handing it over');
    // Reload: my edit is dropped, their settings are shown.
    fireEvent.click(screen.getByTestId('conflict-reload'));
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>('settings-prefix').value).toBe(catalogue.prefix);
    });
  });

  it('BUG-05: the template editor names the part of the template changed', async () => {
    const template = fakeIncidentTemplate({ id: 't-1', code: null, labels: { en: 'VPN' } });
    let saved = false;
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        'GET /api/v1/incidents/categories': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/custom-fields': { body: [] },
        'GET /api/v1/incidents/templates': () => ({
          body: [
            saved
              ? { ...template, description: 'Theirs', version: template.version + 1 }
              : template,
          ],
        }),
        'PATCH /api/v1/incidents/templates/t-1': () => {
          saved = true;
          return stale(template.version + 1);
        },
      },
    });
    open('/admin/incidents/templates');
    fireEvent.click(await screen.findByTestId('tpl-admin-edit-t-1'));
    fireEvent.change(await screen.findByTestId('tpl-editor-group'), {
      target: { value: 'Network' },
    });
    fireEvent.click(screen.getByTestId('tpl-editor-save'));
    await expectNamed('Description');
  });

  it('BUG-05: branding names the setting another admin changed', async () => {
    const base: BrandingSettings = {
      ...fakeBranding(),
      chosen_primary_colour: null,
      chosen_gradient: null,
      logo_file_id: null,
      logo_dark_file_id: null,
      icon_file_id: null,
      version: 1,
    };
    let saved = false;
    api({
      me: ADMIN,
      routes: {
        'GET /api/v1/organization/branding/settings': () => ({
          body: saved ? { ...base, portal_name: { en: 'Help centre' }, version: 2 } : base,
        }),
        'GET /api/v1/organization/domains': { body: { subdomain: null, items: [] } },
        'POST /api/v1/organization/branding/check': {
          body: { passes: true, checks: [], suggested_primary: null, suggested_gradient: null },
        },
        'PUT /api/v1/organization/branding/settings': () => {
          saved = true;
          return stale(2);
        },
      },
    });
    open('/admin/branding');
    fireEvent.change(await screen.findByTestId('branding-product_name-en'), {
      target: { value: 'Acme Desk' },
    });
    await waitFor(() => {
      expect(screen.getByTestId('branding-save').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('branding-save'));
    await expectNamed('Portal name');
  });

  it('BUG-05: an incident move someone beat names who and what changed', async () => {
    const item = fakeIncident();
    const path = `/api/v1/incidents/${item.id}`;
    let moved = false;
    const theirs: Incident = { ...item, priority: 'p1', version: item.version + 1 };
    const fake = api({
      me: ADMIN,
      routes: {
        'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
        'GET /api/v1/incidents/templates': { body: [fakeIncidentTemplate()] },
        'GET /api/v1/incidents/categories': { body: [] },
        'GET /api/v1/organization/groups': { body: [] },
        'GET /api/v1/organization/sites': { body: [] },
        'GET /api/v1/realtime/lists/incidents': { body: { channels: [] } },
        [`GET ${path}`]: () => ({ body: moved ? theirs : item }),
        [`POST ${path}/actions/start_work`]: () => {
          if (moved)
            return { body: { ...theirs, status: 'in_progress', version: theirs.version + 1 } };
          moved = true;
          return stale(theirs.version);
        },
      },
    });
    open(`/incidents/${item.id}`);
    fireEvent.click(await screen.findByTestId('inc-action-start_work'));
    await expectNamed('Priority');
    // Keep mine: the move again, on the version saved now.
    fireEvent.click(screen.getByTestId('conflict-keep-mine'));
    await waitFor(() => {
      expect(fake.find('POST', `${path}/actions/start_work`)).toHaveLength(2);
    });
    expect(fake.find('POST', `${path}/actions/start_work`)[1]?.headers.get('If-Match')).toBe(
      `"${String(theirs.version)}"`,
    );
  });
});
