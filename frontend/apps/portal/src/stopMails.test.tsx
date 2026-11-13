import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi } from '@supportx/api-client/testing';

import { App } from './App';

// WP-046a S6 (REQ-INC-066): stopping mails to an address kept informed, without sign-in.
const TOKEN = 'B'.repeat(21) + '-_' + 'y'.repeat(20);
const PEEK = 'POST /api/v1/public/notify-links/peek';
const STOP = 'POST /api/v1/public/notify-links/stop';

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('Stop these e-mails', () => {
  it('asks first, never stops on opening, and stops only on the button', async () => {
    window.history.pushState({}, '', `/stop-mails?t=acme#${TOKEN}`);
    const fake = fakeApi({
      [PEEK]: { body: { display_id: 'INC-12', address: 'b***@acme.test' } },
      [STOP]: { status: 204, body: null },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('stop-mails-ask')).textContent).toBe(
      'Stop sending updates about INC-12 to b***@acme.test?',
    );
    expect(window.location.hash).toBe(''); // the token is off the address bar
    expect(fake.find('GET', '/api/v1/auth/me')).toHaveLength(0); // no session asked for
    expect(fake.find('POST', '/api/v1/public/notify-links/peek')[0]?.body).toEqual({
      token: TOKEN,
      tenant: 'acme',
    });
    expect(fake.find('POST', '/api/v1/public/notify-links/stop')).toHaveLength(0);
    fireEvent.click(screen.getByTestId('stop-mails-button'));
    expect((await screen.findByTestId('stop-mails-done')).textContent).toContain('INC-12');
    expect(fake.find('POST', '/api/v1/public/notify-links/stop')).toHaveLength(1);
  });

  it('a link that no longer works says so, with nothing to press', async () => {
    window.history.pushState({}, '', `/stop-mails#${TOKEN}`);
    const fake = fakeApi({
      [PEEK]: {
        status: 404,
        body: {
          type: 'about:blank',
          title: 'Not Found',
          status: 404,
          code: 'notify_link_not_found',
          message_key: 'errors.notify_link_not_found',
          params: {},
          errors: [],
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    expect((await screen.findByTestId('stop-mails-gone')).textContent).toContain(
      'This link no longer works',
    );
    expect(screen.queryByTestId('stop-mails-button')).toBeNull();
  });

  it('in Arabic the masked address is isolated in the sentence (lane C)', async () => {
    window.localStorage.setItem('supportx.locale', 'ar');
    window.history.pushState({}, '', `/stop-mails#${TOKEN}`);
    const fake = fakeApi({
      [PEEK]: { body: { display_id: 'INC-12', address: 'b***@acme.test' } },
    });
    restore = () => {
      fake.restore();
      window.localStorage.removeItem('supportx.locale');
    };
    render(<App />);
    const ask = (await screen.findByTestId('stop-mails-ask')).textContent;
    expect(ask).toContain('\u2068b***@acme.test\u2069');
  });

  it('an outage on the button keeps the button for another try', async () => {
    window.history.pushState({}, '', `/stop-mails#${TOKEN}`);
    const fake = fakeApi({
      [PEEK]: { body: { display_id: 'INC-12', address: 'b***@acme.test' } },
      [STOP]: {
        status: 503,
        body: {
          type: 'about:blank',
          title: 'Service Unavailable',
          status: 503,
          code: 'service_unavailable',
          message_key: 'errors.service_unavailable',
          params: {},
          errors: [],
        },
      },
    });
    restore = fake.restore;
    render(<App />);
    fireEvent.click(await screen.findByTestId('stop-mails-button'));
    expect(await screen.findByTestId('stop-mails-failed')).toBeTruthy();
    expect(screen.queryByTestId('stop-mails-gone')).toBeNull();
    expect(screen.getByTestId('stop-mails-button')).toBeTruthy();
  });
});
