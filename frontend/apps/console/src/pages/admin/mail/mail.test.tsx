import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeMailbox } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi, fakeSession, problem } from '../../../test/api';
import { browser } from './navigation';

// WP-024 screens: Admin › Mail.
let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const BASE = '/api/v1/integrations/mailboxes';

describe('Admin › Mail', () => {
  afterEach(() => {
    restore();
  });

  it('says why a mailbox cannot be read and how many messages wait', async () => {
    window.history.pushState({}, '', '/admin/mail');
    api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: {
          body: [fakeMailbox({ state: 'failing', state_reason: 'imap_login_failed', held: 3 })],
        },
      },
    });
    render(<App />);
    const row = await screen.findByTestId('mailbox-it@acme.test');
    expect(within(row).getByTestId('mailbox-state').textContent).toBe('Failing');
    expect(within(row).getByTestId('mailbox-reason').textContent).toBe(
      'The mail server refused the user name or password',
    );
    expect(within(row).getByTestId('mailbox-held').textContent).toBe(
      '3 messages waiting for an admin',
    );
  });

  it('refuses a connection without encryption at the form, before saving', async () => {
    window.history.pushState({}, '', '/admin/mail');
    const fake = api({ me: ADMIN, routes: { [`GET ${BASE}`]: { body: [] } } });
    render(<App />);
    fireEvent.click(await screen.findByTestId('mailbox-add'));
    const editor = await screen.findByTestId('mailbox-editor');
    for (const [name, value] of [
      ['address', 'it@acme.test'],
      ['host', 'imap.acme.test'],
      ['username', 'it@acme.test'],
      ['password', 'secret'],
    ] as const) {
      fireEvent.change(within(editor).getByTestId(`mailbox-${name}`), { target: { value } });
    }
    const security = within(editor).getByRole('combobox', { name: 'Encryption' });
    fireEvent.mouseDown(security);
    fireEvent.click(await screen.findByTitle('No encryption'));
    expect(
      await within(editor).findByText(
        'A connection without encryption is refused unless you allow it.',
      ),
    ).toBeTruthy();
    expect(within(editor).getByTestId('mailbox-save').hasAttribute('disabled')).toBe(true);
    fireEvent.click(within(editor).getByTestId('mailbox-allow_plain'));
    await waitFor(() => {
      expect(within(editor).getByTestId('mailbox-save').hasAttribute('disabled')).toBe(false);
    });
    expect(within(editor).getByRole<HTMLInputElement>('spinbutton').value).toBe('143');
    expect(fake.find('POST', BASE)).toHaveLength(0);
  });

  it('shows the server’s refusal under the field it names', async () => {
    window.history.pushState({}, '', '/admin/mail');
    api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: { body: [] },
        [`POST ${BASE}`]: {
          status: 409,
          body: problem(409, 'mailbox_address_taken'),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('mailbox-add'));
    const editor = await screen.findByTestId('mailbox-editor');
    for (const [name, value] of [
      ['address', 'it@acme.test'],
      ['host', 'imap.acme.test'],
      ['username', 'it@acme.test'],
      ['password', 'secret'],
    ] as const) {
      fireEvent.change(within(editor).getByTestId(`mailbox-${name}`), { target: { value } });
    }
    await act(async () => {
      fireEvent.click(within(editor).getByTestId('mailbox-save'));
      await Promise.resolve();
    });
    const note = await within(editor).findByTestId('mailbox-address-field');
    await waitFor(() => {
      expect(note.textContent).toContain('Another mailbox already reads this address.');
    });
  });

  it('lists held mail with its reason and hands it in again', async () => {
    window.history.pushState({}, '', '/admin/mail');
    const box = fakeMailbox({ held: 2 });
    const waiting = `${BASE}/${box.id}/waiting`;
    const fake = api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: { body: [box] },
        [`GET ${waiting}`]: {
          body: [
            {
              message_id: 'flood@acme.test',
              sender: 'sara@acme.test',
              subject: 'Printer jams',
              outcome: 'held',
              reason: 'sender_rate',
              reason_params: {},
              received_at: '2026-10-28T09:00:00Z',
              releasable: true,
            },
            {
              message_id: 'other@acme.test',
              sender: 'tech@acme.test',
              subject: 'Re: [INC-7] x',
              outcome: 'held',
              reason: 'not_requester',
              reason_params: {},
              received_at: '2026-10-28T09:05:00Z',
              releasable: false,
            },
          ],
        },
        [`POST ${waiting}/release`]: {
          body: { outcome: 'created', reason: null, reason_params: {} },
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('mailbox-review'));
    const drawer = await screen.findByTestId('mail-waiting');
    const items = await within(drawer).findAllByTestId('mail-waiting-item');
    expect(items).toHaveLength(2);
    const [flood, other] = items as [HTMLElement, HTMLElement];
    expect(within(flood).getByTestId('mail-waiting-reason').textContent).toContain(
      'Many messages from this sender in an hour',
    );
    expect(within(other).queryByTestId('mail-waiting-release')).toBeNull(); // discard only
    expect(within(other).getByTestId('mail-waiting-reason').textContent).toContain(
      'Staff reply in the console.',
    );
    fireEvent.click(within(flood).getByTestId('mail-waiting-release'));
    await waitFor(() => {
      expect(fake.find('POST', `${waiting}/release`)).toHaveLength(1);
    });
    expect(fake.find('POST', `${waiting}/release`)[0]?.body).toEqual({
      message_id: 'flood@acme.test',
    });
    expect(await screen.findByText('Handed in again: Incident created')).toBeTruthy();
  });

  it('names the fields a refused incident needs, never a raw key', async () => {
    window.history.pushState({}, '', '/admin/mail');
    const box = fakeMailbox({ held: 1 });
    api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: { body: [box] },
        [`GET ${BASE}/${box.id}/waiting`]: {
          body: [
            {
              message_id: 'm@acme.test',
              sender: 'sara@acme.test',
              subject: 'Printer jams',
              outcome: 'held',
              reason: 'mail_fields_needed',
              reason_params: { fields: 'category_id,custom.asset_tag' },
              received_at: '2026-10-28T09:00:00Z',
              releasable: true,
            },
          ],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('mailbox-review'));
    const reason = await screen.findByTestId('mail-waiting-reason');
    expect(reason.textContent).toContain('it needs Category and 1 other field');
    expect(reason.textContent).not.toContain('custom.asset_tag');
  });

  it('technicians do not see the tab', async () => {
    window.history.pushState({}, '', '/admin/users');
    api({ routes: {} });
    render(<App />);
    expect(await screen.findByTestId('user-menu')).toBeTruthy();
    expect(screen.queryByText('Mail')).toBeNull();
  });

  // --- Microsoft 365 and Gmail (WP-024 session 2) ------------------------------------------------

  it('adds a Gmail mailbox with the redirect address to register', async () => {
    window.history.pushState({}, '', '/admin/mail');
    const fake = api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: { body: [] },
        [`POST ${BASE}`]: {
          status: 201,
          body: fakeMailbox({ protocol: 'gmail', needs_sign_in: true, host: null }),
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('mailbox-add'));
    const editor = await screen.findByTestId('mailbox-editor');
    fireEvent.mouseDown(within(editor).getByRole('combobox', { name: 'Kind of mailbox' }));
    fireEvent.click(await screen.findByTitle('Gmail'));
    expect(within(editor).queryByTestId('mailbox-host')).toBeNull();
    expect(within(editor).queryByTestId('mailbox-directory_id')).toBeNull(); // Microsoft only
    expect(within(editor).getByTestId('mailbox-redirect-address').textContent).toBe(
      `${window.location.origin}/api/v1/integrations/oauth/callback`,
    );
    for (const [name, value] of [
      ['address', 'help@acme.test'],
      ['client_id', 'app-1'],
      ['client_secret', 's3cret'],
    ] as const) {
      fireEvent.change(within(editor).getByTestId(`mailbox-${name}`), { target: { value } });
    }
    fireEvent.click(within(editor).getByTestId('mailbox-save'));
    await waitFor(() => {
      expect(fake.find('POST', BASE)).toHaveLength(1);
    });
    expect(fake.find('POST', BASE)[0]?.body).toMatchObject({
      address: 'help@acme.test',
      protocol: 'gmail',
      client_id: 'app-1',
      client_secret: 's3cret',
      auth_model: 'delegated',
      credential_kind: 'secret',
    });
    expect(fake.find('POST', BASE)[0]?.body).not.toHaveProperty('host');
  });

  it('asks Microsoft 365 for its directory and shows no redirect with app permission', async () => {
    window.history.pushState({}, '', '/admin/mail');
    api({ me: ADMIN, routes: { [`GET ${BASE}`]: { body: [] } } });
    render(<App />);
    fireEvent.click(await screen.findByTestId('mailbox-add'));
    const editor = await screen.findByTestId('mailbox-editor');
    fireEvent.mouseDown(within(editor).getByRole('combobox', { name: 'Kind of mailbox' }));
    fireEvent.click(await screen.findByTitle('Microsoft 365'));
    expect(within(editor).getByTestId('mailbox-directory_id')).toBeTruthy();
    expect(within(editor).queryByTestId('mailbox-redirect')).toBeNull(); // nobody signs in
    fireEvent.mouseDown(within(editor).getByRole('combobox', { name: 'App credential' }));
    fireEvent.click(await screen.findByTitle('Certificate'));
    expect(within(editor).getByText('Certificate and private key (PEM)')).toBeTruthy();
    expect(within(editor).queryByTestId('mailbox-credential_expires_at')).toBeNull(); // read from it
  });

  it('sends the admin to the provider to sign in as the mailbox', async () => {
    window.history.pushState({}, '', '/admin/mail');
    const go = vi.spyOn(browser, 'go').mockImplementation(() => undefined);
    try {
      const box = fakeMailbox({ protocol: 'gmail', needs_sign_in: true, signed_in: false });
      const fake = api({
        me: ADMIN,
        routes: {
          [`GET ${BASE}`]: { body: [box] },
          [`POST ${BASE}/${box.id}/sign-in`]: {
            body: { authorize_url: 'https://accounts.test/auth?state=x' },
          },
        },
      });
      render(<App />);
      const row = await screen.findByTestId('mailbox-it@acme.test');
      expect(within(row).getByTestId('mailbox-needs-sign-in').textContent).toBe(
        'Waiting for someone to sign in as the mailbox',
      );
      fireEvent.click(within(row).getByTestId('mailbox-sign-in'));
      await waitFor(() => {
        expect(go).toHaveBeenCalledWith('https://accounts.test/auth?state=x');
      });
      expect(fake.find('POST', `${BASE}/${box.id}/sign-in`)).toHaveLength(1);
    } finally {
      go.mockRestore();
    }
  });

  it('says why a sign-in did not work when the provider sends the admin back', async () => {
    window.history.pushState({}, '', '/admin/mail?sign_in=oauth_wrong_account&mailbox=x');
    api({ me: ADMIN, routes: { [`GET ${BASE}`]: { body: [] } } });
    render(<App />);
    expect(
      await screen.findByText(
        "The sign-in did not work: The sign-in was with another account than the mailbox's own.",
      ),
    ).toBeTruthy();
    await waitFor(() => {
      expect(window.location.search).toBe('');
    });
  });

  it('warns ahead of an expiring app secret', async () => {
    window.history.pushState({}, '', '/admin/mail');
    const soon = new Date(Date.now() + 3 * 86_400_000).toISOString();
    api({
      me: ADMIN,
      routes: {
        [`GET ${BASE}`]: {
          body: [fakeMailbox({ protocol: 'graph', credential_expires_at: soon })],
        },
      },
    });
    render(<App />);
    const row = await screen.findByTestId('mailbox-it@acme.test');
    expect(within(row).getByTestId('mailbox-protocol').textContent).toBe('Microsoft 365');
    expect(within(row).getByTestId('mailbox-credential-expiry').textContent).toMatch(
      /^The app's secret or certificate expires /,
    );
  });
});
