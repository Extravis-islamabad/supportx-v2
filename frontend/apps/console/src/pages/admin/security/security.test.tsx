import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { IdentitySettings, Invitation, SsoProvider } from '@supportx/api-client';
import { fakeSession, problem } from '@supportx/api-client/testing';

import { App } from '../../../App';
import { consoleApi } from '../../../test/api';

// WP-039 session 1: Admin › Sign-in and security (REQ-SEC-007, 008, 013, 017, 029).

let restore: () => void = () => undefined;
function api(...args: Parameters<typeof consoleApi>) {
  const fake = consoleApi(...args);
  restore = fake.restore;
  return fake;
}

const ADMIN = fakeSession({ roles: ['tenant_admin'] });
const DEFAULTS: IdentitySettings = {
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
  password_policy_state: 'default',
  password_policy_error: null,
  version: 0,
};

function invitation(overrides: Partial<Invitation> = {}): Invitation {
  return {
    id: 'i1',
    user_id: 'u1',
    email: 'ina@acme.test',
    status: 'pending',
    delivery: 'email',
    sent_at: '2026-10-27T10:00:00Z',
    expires_at: '2026-11-03T10:00:00Z',
    accepted_at: null,
    sends: 1,
    earlier_links_work: false,
    version: 1,
    ...overrides,
  };
}

function provider(overrides: Partial<SsoProvider> = {}): SsoProvider {
  return {
    id: 'p1',
    protocol: 'oidc',
    preset: 'entra',
    display_name: 'Acme Entra ID',
    state: 'draft',
    domains: ['acme.test'],
    email_redirect: false,
    settings: { issuer: 'https://login.example.test/acme/v2.0', client_id: 'supportx' },
    last_check: { ok: true, problems: [], checked_at: '2026-10-27T10:00:00Z' },
    tested_at: null,
    switched_on_at: null,
    service_provider_metadata_url: 'http://kc.test/realms/supportx/broker/sx-a/endpoint/descriptor',
    redirect_uri: 'http://kc.test/realms/supportx/broker/sx-a/endpoint',
    version: 1,
    ...overrides,
  };
}

function routes(extra: Parameters<typeof consoleApi>[0] = {}) {
  return {
    me: ADMIN,
    ...extra,
    routes: {
      'GET /api/v1/identity/settings': { body: DEFAULTS },
      'GET /api/v1/identity/sso': { body: { items: [] } },
      'GET /api/v1/identity/invitations': { body: { items: [] } },
      ...extra.routes,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  window.history.pushState({}, '', '/admin/security');
});
afterEach(() => {
  restore();
  vi.restoreAllMocks();
});

describe('sessions and people creation', () => {
  it('REQ-SEC-029: timeouts show in minutes and hours, a bad one is refused at the field at once, a good one is saved in seconds', async () => {
    const fake = api(
      routes({
        routes: {
          'PUT /api/v1/identity/settings': ({ body }) => ({
            body: { ...(body as IdentitySettings), version: 1 },
            headers: { ETag: '"1"' },
          }),
        },
      }),
    );
    render(<App />);
    const idle = await screen.findByTestId('security-portal-idle');
    expect((idle as HTMLInputElement).value).toBe('30');
    expect(screen.getByTestId<HTMLInputElement>('security-console-absolute').value).toBe('12');
    fireEvent.change(idle, { target: { value: '2' } });
    expect(
      within(screen.getByTestId('security-portal-idle-field')).getByRole('alert').textContent,
    ).toBe('Use between 5 and 1440 minutes.');
    expect(screen.getByTestId('security-sessions-save').hasAttribute('disabled')).toBe(true);
    fireEvent.change(idle, { target: { value: '15' } });
    expect(
      within(screen.getByTestId('security-portal-idle-field')).queryByRole('alert'),
    ).toBeNull();
    fireEvent.click(screen.getByTestId('security-sessions-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/settings')).toHaveLength(1);
    });
    const put = fake.find('PUT', '/api/v1/identity/settings')[0];
    expect(put?.headers.get('If-Match')).toBe('"0"');
    expect((put?.body as IdentitySettings).portal_idle_seconds).toBe(900);
    expect(await screen.findByText('Sign-in settings saved.')).toBeTruthy();
  });

  it('REQ-SEC-013: turning people creation off says who can still sign in', async () => {
    api(routes());
    render(<App />);
    fireEvent.click(await screen.findByTestId('security-create-people'));
    expect(
      screen.getByText(
        'Only people you added, imported or invited can sign in. Others are told to contact your service desk.',
      ),
    ).toBeTruthy();
  });

  it('the tab is offered only to people who may manage sign-in and security', async () => {
    api({ me: fakeSession({ roles: ['technician'] }) });
    window.history.pushState({}, '', '/admin');
    render(<App />);
    await screen.findByTestId('user-name');
    expect(screen.queryByRole('tab', { name: 'Sign-in and security' })).toBeNull();
  });
});

describe('password policy (WP-039 session 2, REQ-SEC-005)', () => {
  it('a length under the floor is refused at the field at once; only the policy fields are saved, and the state shows', async () => {
    const fake = api(
      routes({
        routes: {
          'PUT /api/v1/identity/settings': ({ body }) => ({
            body: {
              ...DEFAULTS,
              ...(body as Partial<IdentitySettings>),
              password_policy_state: 'applying',
              version: 1,
            },
            headers: { ETag: '"1"' },
          }),
        },
      }),
    );
    render(<App />);
    const length = await screen.findByTestId('security-password_min_length');
    expect((length as HTMLInputElement).value).toBe('12');
    expect(screen.getByTestId('security-password-state').textContent).toBe('Installation default');
    fireEvent.change(length, { target: { value: '6' } });
    expect(
      within(screen.getByTestId('security-password_min_length-field')).getByRole('alert')
        .textContent,
    ).toBe('Use between 8 and 64.');
    expect(screen.getByTestId('security-password-save').hasAttribute('disabled')).toBe(true);
    fireEvent.change(length, { target: { value: '14' } });
    fireEvent.click(screen.getByTestId('security-password_breached_check'));
    fireEvent.click(screen.getByTestId('security-password-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/settings')).toHaveLength(1);
    });
    const sent = fake.find('PUT', '/api/v1/identity/settings')[0]?.body as Record<string, unknown>;
    expect(sent.password_min_length).toBe(14);
    expect(sent.password_breached_check).toBe(false);
    expect('portal_idle_seconds' in sent).toBe(false); // the sessions card's fields are its own
    expect(
      await screen.findByText('Password policy saved. It applies to passwords set from now on.'),
    ).toBeTruthy();
    expect(screen.getByTestId('security-password-state').textContent).toBe('Being applied');
  });

  it('a save sends the version read; when another admin saved first the conflict dialog asks, and keeping mine saves on their version', async () => {
    let reads = 0;
    let puts = 0;
    const fake = api(
      routes({
        routes: {
          'GET /api/v1/identity/settings': () => {
            reads += 1;
            return { body: { ...DEFAULTS, version: reads === 1 ? 0 : 1 } };
          },
          'PUT /api/v1/identity/settings': () => {
            puts += 1;
            return puts === 1
              ? {
                  status: 409,
                  body: problem(409, 'version_conflict', { params: { expected_version: 0 } }),
                }
              : { body: { ...DEFAULTS, password_min_length: 16, version: 2 } };
          },
        },
      }),
    );
    render(<App />);
    fireEvent.change(await screen.findByTestId('security-password_min_length'), {
      target: { value: '16' },
    });
    fireEvent.click(screen.getByTestId('security-password-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/settings')).toHaveLength(1);
    });
    expect(fake.find('PUT', '/api/v1/identity/settings')[0]?.headers.get('If-Match')).toBe('"0"');
    // The shared conflict dialog (QA WP-029 BUG-05), not a passing message.
    expect(await screen.findByText('Someone else changed this')).toBeTruthy();
    await waitFor(() => {
      expect(reads).toBeGreaterThan(1); // their version, fetched again
    });
    // What was typed is kept, to save again on top of their change.
    expect(screen.getByTestId<HTMLInputElement>('security-password_min_length').value).toBe('16');
    fireEvent.click(screen.getByTestId('conflict-keep-mine'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/settings')).toHaveLength(2);
    });
    expect(fake.find('PUT', '/api/v1/identity/settings')[1]?.headers.get('If-Match')).toBe('"1"');
  });

  it('a policy the sign-in service did not take says why and is applied again', async () => {
    const fake = api(
      routes({
        routes: {
          'GET /api/v1/identity/settings': {
            body: {
              ...DEFAULTS,
              version: 2,
              password_policy_state: 'failed',
              password_policy_error: 'password_policy_keycloak_unavailable',
            },
          },
          'POST /api/v1/identity/settings/password-policy/apply': {
            body: { ...DEFAULTS, version: 2, password_policy_state: 'applying' },
          },
        },
      }),
    );
    render(<App />);
    const failed = await screen.findByTestId('security-password-failed');
    expect(failed.textContent).toContain(
      'The sign-in service could not be reached. Apply again in a moment.',
    );
    fireEvent.click(screen.getByTestId('security-password-apply'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/settings/password-policy/apply')).toHaveLength(1);
    });
    await waitFor(() => {
      expect(screen.queryByTestId('security-password-failed')).toBeNull();
    });
  });

  it("on a shared installation the policy is the platform's and cannot be edited", async () => {
    api(
      routes({
        routes: {
          'GET /api/v1/identity/settings': {
            body: { ...DEFAULTS, password_policy_editable: false },
          },
        },
      }),
    );
    render(<App />);
    const length = await screen.findByTestId('security-password_min_length');
    expect(length.hasAttribute('disabled')).toBe(true);
    expect(screen.queryByTestId('security-password-save')).toBeNull();
    expect(screen.getByTestId('security-password').textContent).toContain(
      'the platform sets its password policy',
    );
  });
});

describe('invitations (WP-039 session 2, REQ-SEC-018..020)', () => {
  it('lists invitations with their state; a waiting one is sent again or withdrawn', async () => {
    const fake = api(
      routes({
        routes: {
          'GET /api/v1/identity/invitations': {
            body: {
              items: [
                invitation(),
                invitation({ id: 'i2', email: 'sam@acme.test', status: 'accepted' }),
              ],
            },
          },
          'POST /api/v1/identity/invitations/i1/resend': { body: invitation({ version: 2 }) },
          'POST /api/v1/identity/invitations/i1/revoke': {
            body: invitation({ version: 2, status: 'revoked' }),
          },
        },
      }),
    );
    render(<App />);
    const list = await screen.findByTestId('security-invitations-list');
    await within(list).findByText('ina@acme.test');
    expect(
      within(list)
        .getAllByTestId('invitation-status')
        .map((tag) => tag.textContent),
    ).toEqual(['Waiting', 'Accepted']);
    expect(within(list).getAllByTestId('invitation-resend')).toHaveLength(1); // not the accepted
    fireEvent.click(within(list).getByTestId('invitation-resend'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/invitations/i1/resend')).toHaveLength(1);
    });
    expect(
      fake.find('POST', '/api/v1/identity/invitations/i1/resend')[0]?.headers.get('If-Match'),
    ).toBe('"1"');
    expect(await screen.findByText('Invitation sent again.')).toBeTruthy();
    fireEvent.click(within(list).getByTestId('invitation-revoke'));
    const confirm = await screen.findAllByRole('button', { name: 'Withdraw' });
    fireEvent.click(confirm.at(-1) ?? document.body); // the pop-up's, after the row's
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/invitations/i1/revoke')).toHaveLength(1);
    });
  });

  it('says when links sent earlier still work after sending again', async () => {
    // Keycloak cannot withdraw one link (proved on 26.8.1): for an account that existed before
    // the invitation, the earlier e-mail's link works until it expires (product owner).
    const after = invitation({ version: 2, sends: 2, earlier_links_work: true });
    api(
      routes({
        routes: {
          'GET /api/v1/identity/invitations': { body: { items: [invitation()] } },
          'POST /api/v1/identity/invitations/i1/resend': { body: after },
        },
      }),
    );
    render(<App />);
    const list = await screen.findByTestId('security-invitations-list');
    await within(list).findByText('ina@acme.test');
    expect(within(list).queryByTestId('invitation-earlier-links')).toBeNull();
    fireEvent.click(within(list).getByTestId('invitation-resend'));
    expect(
      await screen.findByText(
        'Invitation sent again. This person had an account before the invitation, so links sent earlier also still work until they expire.',
      ),
    ).toBeTruthy();
  });

  it('shows on the list that earlier links still work', async () => {
    api(
      routes({
        routes: {
          'GET /api/v1/identity/invitations': {
            body: { items: [invitation({ sends: 2, earlier_links_work: true })] },
          },
        },
      }),
    );
    render(<App />);
    const note = await screen.findByTestId('invitation-earlier-links');
    expect(note.textContent).toBe('Links sent earlier also still work until they expire.');
  });

  it('how long links work is checked at once and saved alone', async () => {
    const fake = api(
      routes({
        routes: {
          'PUT /api/v1/identity/settings': ({ body }) => ({
            body: { ...DEFAULTS, ...(body as Partial<IdentitySettings>), version: 1 },
          }),
        },
      }),
    );
    render(<App />);
    const days = await screen.findByTestId('security-invitation-days');
    fireEvent.change(days, { target: { value: '45' } });
    expect(
      within(screen.getByTestId('security-invitation-days-field')).getByRole('alert').textContent,
    ).toBe('Use between 1 and 30 days.');
    fireEvent.change(days, { target: { value: '14' } });
    fireEvent.click(screen.getByTestId('security-invitation-days-save'));
    await waitFor(() => {
      expect(fake.find('PUT', '/api/v1/identity/settings')[0]?.body).toEqual({
        invitation_valid_days: 14,
      });
    });
  });
});

describe('single sign-on', () => {
  it('REQ-SEC-008: an Entra ID set-up is added with its secret, and a refusal says why at the field', async () => {
    let attempts = 0;
    const fake = api(
      routes({
        routes: {
          'POST /api/v1/identity/sso': () => {
            attempts += 1;
            return attempts === 1
              ? {
                  status: 422,
                  body: problem(422, 'validation_failed', {
                    errors: [
                      {
                        field: 'client_secret',
                        code: 'sso_client_rejected',
                        message_key: 'errors.field.sso_client_rejected',
                        params: {},
                      },
                    ],
                  }),
                }
              : { status: 201, body: provider() };
          },
        },
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByTestId('sso-add'));
    const editor = await screen.findByTestId('sso-editor');
    fireEvent.change(within(editor).getByTestId('sso-display_name'), {
      target: { value: 'Acme Entra ID' },
    });
    const domains = within(editor).getByRole('combobox');
    fireEvent.change(domains, { target: { value: 'acme.test,' } });
    fireEvent.change(within(editor).getByTestId('sso-issuer'), {
      target: { value: 'https://login.example.test/acme/v2.0' },
    });
    fireEvent.change(within(editor).getByTestId('sso-client_id'), {
      target: { value: 'supportx' },
    });
    fireEvent.change(within(editor).getByTestId('sso-client_secret'), {
      target: { value: 'wrong' },
    });
    await waitFor(() => {
      expect(screen.getByTestId('sso-save').hasAttribute('disabled')).toBe(false);
    });
    fireEvent.click(screen.getByTestId('sso-save'));
    expect(
      (await within(screen.getByTestId('sso-client_secret-field')).findByRole('alert')).textContent,
    ).toBe('The identity provider refused this client ID and secret.');
    fireEvent.change(within(editor).getByTestId('sso-client_secret'), {
      target: { value: 'right' },
    });
    expect(within(screen.getByTestId('sso-client_secret-field')).queryByRole('alert')).toBeNull();
    fireEvent.click(screen.getByTestId('sso-save'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/sso')).toHaveLength(2);
    });
    const [first, second] = fake.find('POST', '/api/v1/identity/sso');
    expect(second?.body).toMatchObject({
      preset: 'entra',
      domains: ['acme.test'],
      client_secret: 'right',
    });
    // The same attempt: the same Idempotency-Key.
    expect(second?.headers.get('Idempotency-Key')).toBe(first?.headers.get('Idempotency-Key'));
  });

  it('a public mail domain is refused as it is typed', async () => {
    api(routes());
    render(<App />);
    fireEvent.click(await screen.findByTestId('sso-add'));
    const editor = await screen.findByTestId('sso-editor');
    const domains = within(editor).getByRole('combobox');
    fireEvent.change(domains, { target: { value: 'not a domain,' } });
    expect(
      within(screen.getByTestId('sso-domains-field')).getByRole('alert').textContent,
    ).toContain('is not a domain name');
  });

  it('REQ-SEC-007/008: a set-up is tested with a link for a private window before it can be switched on', async () => {
    const open = vi.spyOn(window, 'open');
    let status = 'pending';
    api(
      routes({
        routes: {
          'GET /api/v1/identity/sso': { body: { items: [provider()] } },
          'POST /api/v1/identity/sso/p1/tests': {
            body: { test_id: 't1', url: 'http://kc.test/auth?kc_idp_hint=sx-a' },
          },
          'GET /api/v1/identity/sso/p1/tests/t1': () => ({
            body: {
              status,
              reason: null,
              identity:
                status === 'passed'
                  ? {
                      email: 'alice@acme.test',
                      name: 'Alice Acme',
                      department: 'Finance',
                      site: null,
                    }
                  : null,
            },
          }),
        },
      }),
    );
    render(<App />);
    const row = await screen.findByTestId('sso-Acme Entra ID');
    expect(within(row).getByTestId('sso-state').textContent).toBe('Draft');
    expect(within(row).getByTestId('sso-switch').hasAttribute('disabled')).toBe(true);
    fireEvent.click(within(row).getByTestId('sso-test'));
    const dialog = await screen.findByTestId('sso-test-dialog');
    expect(await within(dialog).findByTestId('sso-test-link')).toBeTruthy();
    expect(within(dialog).getByText(/open it in a private window/)).toBeTruthy();
    // Never in this browser: it is signed in as the admin (the sign-in service would refuse).
    expect(open).not.toHaveBeenCalled();
    status = 'passed';
    expect(
      await within(dialog).findByTestId('sso-test-passed', {}, { timeout: 4000 }),
    ).toBeTruthy();
    expect(within(dialog).getByText('alice@acme.test')).toBeTruthy();
    expect(within(dialog).getByText('Finance')).toBeTruthy();
    expect(within(dialog).getByText('Not sent')).toBeTruthy(); // site
  });

  it('the test lands on a page that needs no session', async () => {
    api({ me: null });
    window.history.pushState({}, '', '/sso-test-done');
    render(<App />);
    expect(await screen.findByTestId('sso-test-done')).toBeTruthy();
  });
});
