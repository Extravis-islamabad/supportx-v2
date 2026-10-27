import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { fakeApi } from '@supportx/api-client/testing';

import { App } from './App';

// WP-039 session 2 (REQ-SEC-006, REQ-SEC-035): "Forgot password?" from the sign-in page.

let restore: () => void = () => undefined;

beforeEach(() => {
  window.history.pushState({}, '', '/password-reset');
});
afterEach(() => {
  restore();
});

describe('password reset page', () => {
  it('needs no session, checks the address at once and always gives the same answer', async () => {
    const fake = fakeApi({
      'POST /api/v1/auth/password-reset': { status: 202 },
    });
    restore = fake.restore;
    render(<App />);
    const page = await screen.findByTestId('password-reset');
    expect(fake.find('GET', '/api/v1/auth/me')).toHaveLength(0); // no session asked for
    fireEvent.change(within(page).getByTestId('reset-email'), {
      target: { value: 'not-an-email' },
    });
    fireEvent.click(within(page).getByTestId('reset-send'));
    expect(within(page).getByRole('alert').textContent).toBe('Enter an email address.');
    expect(fake.find('POST', '/api/v1/auth/password-reset')).toHaveLength(0);
    fireEvent.change(within(page).getByTestId('reset-email'), {
      target: { value: ' pat@acme.test ' },
    });
    fireEvent.click(within(page).getByTestId('reset-send'));
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/auth/password-reset')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/auth/password-reset')[0]?.body).toEqual({
      email: 'pat@acme.test',
    });
    const sent = await screen.findByTestId('reset-sent');
    expect(sent.textContent).toContain(
      'If pat@acme.test has a password here, a link is on its way.',
    );
    expect(within(sent).getByTestId('reset-back').getAttribute('href')).toContain(
      '/auth/login?app=portal',
    );
  });
});
