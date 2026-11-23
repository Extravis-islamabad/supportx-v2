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

// WP-046a S5c (REQ-INC-019): the server's sealed copy, for a crash or another tab (lane C's
// conditions: a quiet note above the first field; nothing replaced without asking).
describe('New incident: the kept draft on the server', () => {
  const DRAFT = 'GET /api/v1/drafts/incident-new';
  const kept = (overrides: Record<string, unknown> = {}) => ({
    form_key: 'incident-new',
    version: 3,
    updated_at: new Date(Date.now() - 10 * 60_000).toISOString(),
    unreadable: false,
    values: { subject: 'Printer on fire' },
    ...overrides,
  });

  it('offers it back; Restore fills the form; nothing is shown when there is none', async () => {
    const fake = consoleApi({ me: ADMIN, routes: { ...ROUTES, [DRAFT]: { body: kept() } } });
    restore = fake.restore;
    render(<App />);
    const note = await screen.findByTestId('kept-draft');
    expect(note.getAttribute('role')).toBe('status');
    expect(note.textContent).toContain('A draft of this form was kept');
    expect(note.querySelector('time')?.getAttribute('title')).toBeTruthy();
    fireEvent.click(screen.getByTestId('kept-draft-restore'));
    await waitFor(() => {
      expect(screen.getByTestId<HTMLInputElement>('inc-subject').value).toBe('Printer on fire');
    });
    expect(screen.queryByTestId('kept-draft')).toBeNull();
  });

  it('asks before replacing what was already typed', async () => {
    const fake = consoleApi({ me: ADMIN, routes: { ...ROUTES, [DRAFT]: { body: kept() } } });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('kept-draft');
    fireEvent.change(screen.getByTestId('inc-subject'), { target: { value: 'Typed first' } });
    fireEvent.click(screen.getByTestId('kept-draft-restore'));
    // The confirmation opens in its own layer (a portal), asking before anything is replaced.
    await waitFor(() => {
      expect(document.querySelector('.ant-modal-confirm-title')?.textContent).toBe(
        "Replace what you've typed with the draft?",
      );
    });
    expect(screen.getByTestId<HTMLInputElement>('inc-subject').value).toBe('Typed first');
  });

  it('an unreadable one offers Discard only, and Discard forgets it on the server', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: {
        ...ROUTES,
        [DRAFT]: { body: kept({ unreadable: true, values: null }) },
        'DELETE /api/v1/drafts/incident-new': { status: 204, body: null },
      },
    });
    restore = fake.restore;
    render(<App />);
    const note = await screen.findByTestId('kept-draft-unreadable');
    expect(note.textContent).toBe('A kept draft of this form could not be read.Discard');
    expect(screen.queryByTestId('kept-draft-restore')).toBeNull();
    fireEvent.click(screen.getByTestId('kept-draft-discard'));
    await waitFor(() => {
      expect(fake.find('DELETE', '/api/v1/drafts/incident-new')).toHaveLength(1);
    });
    expect(screen.queryByTestId('kept-draft-unreadable')).toBeNull();
  });
});
