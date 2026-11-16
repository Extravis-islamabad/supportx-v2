import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi } from '@supportx/api-client/testing';

import { App } from './App';

// WP-057 S2b-2 (REQ-SEC-021): a copied invite link's set-password page, without sign-in.
const TOKEN = 'Q'.repeat(21) + '-_' + 'z'.repeat(20);
const PEEK = 'POST /api/v1/public/invite-links/peek';
const ACCEPT = 'POST /api/v1/public/invite-links/accept';
const RULES = { min_length: 12, upper: true, lower: true, digits: true, special: false };
const GONE = {
  status: 404,
  body: {
    type: 'about:blank',
    title: 'Not Found',
    status: 404,
    code: 'invite_link_invalid',
    message_key: 'errors.invite_link_invalid',
    params: {},
    errors: [],
  },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
}

describe('Set your password from a copied invite link', () => {
  it('takes the token off the address bar first and only ever posts it in the body', async () => {
    window.history.pushState({}, '', `/invite?t=acme#${TOKEN}`);
    const fake = fakeApi({
      [PEEK]: { body: { app: 'portal', rules: RULES } },
      [ACCEPT]: { status: 204, body: null },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('invite-rules')).textContent).toContain('12 characters');
    expect(window.location.hash).toBe(''); // the fragment is cleared
    expect(document.querySelector('meta[name="referrer"]')?.getAttribute('content')).toBe(
      'no-referrer',
    );
    expect(fake.find('GET', '/api/v1/auth/me')).toHaveLength(0); // no session asked for
    const peeked = fake.find('POST', '/api/v1/public/invite-links/peek')[0];
    expect(peeked?.body).toEqual({ token: TOKEN, tenant: 'acme' });
    expect(peeked?.url.href).not.toContain(TOKEN); // never in a URL the API could log
    type('invite-password', 'Fresh-Start-42!x');
    type('invite-again', 'Fresh-Start-42!x');
    fireEvent.click(screen.getByTestId('invite-submit'));
    expect(await screen.findByTestId('invite-done')).toBeTruthy();
    const accepted = fake.find('POST', '/api/v1/public/invite-links/accept');
    expect(accepted).toHaveLength(1);
    expect(accepted[0]?.url.href).not.toContain(TOKEN);
    expect(screen.getByTestId('invite-sign-in').getAttribute('href')).toContain('/auth/login');
  });

  it("says which rule a password breaks, and never sends two that don't match", async () => {
    window.history.pushState({}, '', `/invite#${TOKEN}`);
    const fake = fakeApi({
      [PEEK]: { body: { app: 'portal', rules: RULES } },
      [ACCEPT]: {
        status: 422,
        body: {
          type: 'about:blank',
          title: 'Unprocessable Entity',
          status: 422,
          code: 'validation_failed',
          message_key: 'errors.validation_failed',
          params: {},
          errors: [
            {
              field: 'body.password',
              code: 'password_breached',
              message_key: 'errors.field.password_breached',
              params: {},
            },
          ],
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('invite-rules');
    type('invite-password', 'Password1234!');
    type('invite-again', 'Password1234?');
    fireEvent.click(screen.getByTestId('invite-submit'));
    expect(await screen.findByText('The two passwords are not the same.')).toBeTruthy();
    expect(fake.find('POST', '/api/v1/public/invite-links/accept')).toHaveLength(0);
    type('invite-again', 'Password1234!');
    fireEvent.click(screen.getByTestId('invite-submit'));
    expect((await screen.findByTestId('invite-password-problem')).textContent).toBe(
      'This password is known from data breaches. Choose another.',
    );
  });

  it('a link that does not work says so, with no form', async () => {
    window.history.pushState({}, '', `/invite#${TOKEN}`);
    const fake = fakeApi({ [PEEK]: GONE });
    restore = fake.restore;
    render(<App />);
    expect(await screen.findByTestId('invite-gone')).toBeTruthy();
    expect(screen.queryByTestId('invite-password')).toBeNull();
  });
});
