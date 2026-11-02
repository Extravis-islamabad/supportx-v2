import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Invitation, UserDetail } from '@supportx/api-client';

import { App } from '../../../App';
import { consoleApi, fakeSession, fakeUser } from '../../../test/api';

// WP-039 session 2: the sign-in actions on a person's record (REQ-SEC-006, REQ-SEC-018).

let restore: () => void = () => undefined;
const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });

function person(overrides: Partial<UserDetail>): UserDetail {
  return fakeUser({
    id: 'u-9',
    display_name: 'Ina Vitee',
    email: 'ina@acme.test',
    user_type: 'requester',
    version: 2,
    ...overrides,
  });
}

type Routes = NonNullable<NonNullable<Parameters<typeof consoleApi>[0]>['routes']>;

function open(user: UserDetail, extra: Routes = {}) {
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/access-settings': {
        body: { technician_scope: 'group', answered_at: '2026-10-27T08:00:00Z', version: 1 },
      },
      'GET /api/v1/users': { body: { items: [user], has_more: false, next_cursor: null } },
      'GET /api/v1/organization/sites': { body: [] },
      'GET /api/v1/organization/departments': { body: [] },
      'GET /api/v1/organization/groups': { body: [] },
      'GET /api/v1/users/u-9': { body: user, headers: { ETag: '"2"' } },
      ...extra,
    },
  });
  restore = fake.restore;
  render(<App />);
  return fake;
}

async function actions(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByText('Ina Vitee'));
  return screen.findByTestId('person-sign-in-actions');
}

beforeEach(() => {
  window.history.pushState({}, '', '/admin/users');
});
afterEach(() => {
  restore();
});

const SENT: Invitation = {
  id: 'i1',
  user_id: 'u-9',
  email: 'ina@acme.test',
  status: 'pending',
  delivery: 'email',
  sent_at: '2026-10-27T10:00:00Z',
  expires_at: '2026-11-03T10:00:00Z',
  accepted_at: null,
  sends: 1,
  earlier_links_work: false,
  version: 1,
};

describe('sign-in actions on a person', () => {
  it('someone who never signed in is invited once, with an Idempotency-Key', async () => {
    const fake = open(person({ signed_in_before: false }), {
      'GET /api/v1/identity/invitations': { body: { items: [] } },
      'POST /api/v1/identity/invitations': { status: 201, body: SENT },
    });
    const found = await actions();
    const invite = within(found).getByTestId('person-invite');
    await waitFor(() => {
      expect(invite.hasAttribute('disabled')).toBe(false); // once their invitations are known
    });
    fireEvent.click(invite);
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/invitations')).toHaveLength(1);
    });
    const [sent] = fake.find('POST', '/api/v1/identity/invitations');
    expect(sent?.body).toEqual({ user_id: 'u-9' });
    expect(sent?.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(await screen.findByText('Invitation sent to ina@acme.test.')).toBeDefined();
  });

  it('a waiting invitation shows until when it works and is sent again', async () => {
    const fake = open(person({ signed_in_before: false }), {
      'GET /api/v1/identity/invitations': { body: { items: [SENT] } },
      'POST /api/v1/identity/invitations/i1/resend': { body: { ...SENT, version: 2 } },
    });
    const found = await actions();
    expect(await within(found).findByTestId('person-invite-again')).toBeDefined();
    expect(within(found).queryByTestId('person-invite')).toBeNull();
    expect(found.textContent).toContain('Invited: the link works until');
    fireEvent.click(within(found).getByTestId('person-invite-again'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/invitations/i1/resend')).toHaveLength(1);
    });
  });

  it('someone who has signed in can be asked for a new password, after a confirmation', async () => {
    const fake = open(person({ signed_in_before: true }), {
      'POST /api/v1/identity/people/u-9/require-new-password': { status: 204 },
    });
    const found = await actions();
    expect(fake.find('GET', '/api/v1/identity/invitations')).toHaveLength(0); // nothing to show
    fireEvent.click(within(found).getByTestId('person-require-password'));
    const popup = await waitFor(() => {
      const shown = document.querySelector<HTMLElement>('.ant-popconfirm');
      if (shown === null) throw new Error('no confirmation open');
      return shown;
    });
    expect(popup.textContent).toContain('Their sessions end at once');
    fireEvent.click(within(popup).getByRole('button', { name: 'Require a new password' }));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/identity/people/u-9/require-new-password')).toHaveLength(1);
    });
    expect(
      await screen.findByText('Ina Vitee chooses a new password at their next sign-in.'),
    ).toBeDefined();
  });

  it('nothing is offered for a contact who may not sign in', async () => {
    open(person({ can_sign_in: false, signed_in_before: false }));
    fireEvent.click(await screen.findByText('Ina Vitee'));
    await screen.findByTestId('person-status');
    expect(screen.queryByTestId('person-sign-in-actions')).toBeNull();
  });
});
