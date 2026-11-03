import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { UserDetail } from '@supportx/api-client';
import { fakeApi, fakeEntitlements, fakeSession, fakeUser } from '@supportx/api-client/testing';

import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from './App';

// WP-028 (REQ-PRT-013 AC2/AC3): contact details in My account, as the server allows them.

const ME = '01900000-0000-7000-8000-000000000101';

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

function routes(user: Partial<UserDetail>) {
  return {
    'GET /api/v1/auth/me': { body: fakeSession({ user_type: 'requester', roles: ['requester'] }) },
    'GET /api/v1/entitlements': { body: fakeEntitlements() },
    'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
    'GET /api/v1/account/security': {
      body: {
        has_password: true,
        mfa_mode: 'optional',
        mfa_enrolled: false,
        mfa_due_at: null,
        recovery_codes: false,
        recent_sign_ins: [],
        details_available: true,
      },
    },
    [`GET /api/v1/users/${ME}`]: { body: fakeUser({ phone: '+971 4 555 0101', ...user }) },
  };
}

describe('portal: contact details', () => {
  it('when allowed, a person changes their own numbers with If-Match', async () => {
    window.history.pushState({}, '', '/account');
    const fake = fakeApi({
      ...routes({ contact_editable: true, version: 4 }),
      [`PATCH /api/v1/users/${ME}`]: {
        body: fakeUser({ phone: '+971 4 555 0101', mobile: '+971 50 1', contact_editable: true }),
      },
    });
    restore = fake.restore;
    render(<App />);
    const save = await screen.findByTestId('account-contact-save');
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId('account-mobile'), { target: { value: ' +971 50 1 ' } });
    fireEvent.click(save);
    await waitFor(() => {
      expect(fake.find('PATCH', `/api/v1/users/${ME}`)).toHaveLength(1);
    });
    const [sent] = fake.find('PATCH', `/api/v1/users/${ME}`);
    expect(sent?.body).toEqual({ phone: '+971 4 555 0101', mobile: '+971 50 1' });
    expect(sent?.headers.get('If-Match')).toBe('"4"');
  });

  it('when the organisation does not allow it, the numbers are read-only and say so', async () => {
    window.history.pushState({}, '', '/account');
    const fake = fakeApi(routes({ contact_editable: false }));
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('account-contact-locked')).toBeDefined();
    expect(screen.queryByTestId('account-phone')).toBeNull();
    expect(screen.getByText('+971 4 555 0101')).toBeDefined();
  });

  it('numbers a directory keeps say where they come from', async () => {
    window.history.pushState({}, '', '/account');
    const fake = fakeApi(routes({ contact_editable: false, directory_source: 'entra' }));
    restore = fake.restore;
    render(<App />);
    const note = await screen.findByTestId('account-contact-directory');
    expect(note.textContent).toContain('Microsoft Entra ID');
    expect(screen.queryByTestId('account-contact-locked')).toBeNull();
  });
});

describe('portal: contact details live', () => {
  it('an admin allowing it opens the fields with no reload (rule 5c)', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    let editable = false;
    window.history.pushState({}, '', '/account');
    const fake = fakeApi({
      ...routes({}),
      [`GET /api/v1/users/${ME}`]: () => ({
        body: fakeUser({ phone: '+971 4 555 0101', contact_editable: editable }),
      }),
    });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('account-contact-locked')).toBeDefined();
    editable = true;
    act(() => {
      realtime.publish(':broadcast', { type: 'identity_access.contact_editing_changed', ids: [] });
    });
    expect(await screen.findByTestId('account-phone')).toBeDefined();
  });
});
