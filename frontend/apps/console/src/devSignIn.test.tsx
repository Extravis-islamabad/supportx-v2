import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi } from '@supportx/api-client/testing';

import { App } from './App';

// D-151: the dev-only quick sign-in page, before any session.
let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const PERSONAS = [
  { code: 'admin', email: 'admin@showcase.test', app: 'console', enrolled: true },
  { code: 'new_starter', email: 'newstarter@showcase.test', app: 'portal', enrolled: false },
];

describe('dev quick sign-in page', () => {
  it('says it is not available where the API does not answer', async () => {
    window.history.pushState({}, '', '/dev/sign-in');
    restore = fakeApi({ 'GET /api/v1/auth/dev/personas': { status: 404, body: {} } }).restore;
    render(<App />);
    expect(await screen.findByTestId('dev-sign-in-unavailable')).toBeTruthy();
  });

  it('one button per persona; a refusal is said in words', async () => {
    window.history.pushState({}, '', '/dev/sign-in');
    const fake = fakeApi({
      'GET /api/v1/auth/dev/personas': { body: PERSONAS },
      'POST /api/v1/auth/dev/sign-in': {
        status: 403,
        body: {
          code: 'quick_sign_in_refused',
          message_key: 'errors.quick_sign_in_refused',
          params: { reason: 'credentials_refused' },
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    const admin = await screen.findByTestId('dev-sign-in-admin');
    expect(admin.textContent).toContain('Sign in as Administrator');
    expect(screen.getByTestId('dev-sign-in-new_starter').textContent).toContain(
      'sets up two-step sign-in',
    );
    fireEvent.click(admin);
    const problem = await screen.findByTestId('dev-sign-in-problem');
    expect(problem.textContent).toContain('doesn’t match the seed');
    await waitFor(() => {
      expect(fake.find('POST', '/api/v1/auth/dev/sign-in')).toHaveLength(1);
    });
    expect(fake.find('POST', '/api/v1/auth/dev/sign-in')[0]?.body).toEqual({ persona: 'admin' });
  });

  it('the new starter is told where the set-up link went, and stays on the page', async () => {
    window.history.pushState({}, '', '/dev/sign-in');
    restore = fakeApi({
      'GET /api/v1/auth/dev/personas': { body: PERSONAS },
      'POST /api/v1/auth/dev/sign-in': {
        body: { redirect_to: null, setup_link_sent_to: 'newstarter@showcase.test' },
      },
    }).restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('dev-sign-in-new_starter'));
    const sent = await screen.findByTestId('dev-sign-in-setup-sent');
    expect(sent.textContent).toContain('newstarter@showcase.test');
    expect(sent.textContent).toContain('Mailpit');
    expect(window.location.pathname).toBe('/dev/sign-in');
  });
});
