import { act, fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, call } from '@supportx/api-client';
import { fakeApi, problem } from '@supportx/api-client/testing';

import { renderUi } from '../test/render';
import { ConfirmedPage } from './ConfirmedPage';
import {
  REAUTH_CHANNEL,
  readConfirmedMessage,
  safeReturnTo,
  startConfirmation,
  type ChannelFactory,
} from './confirmation';
import { ReauthDialog } from './ReauthDialog';

// REQ-SEC-027 (WP-057 S2a): a sensitive change confirmed in a pop-up, with lane B's conditions for
// the pop-up's answer (2026-11-13): same origin, this attempt only, exact shape, a safe way back.

const ORIGIN = window.location.origin;
const ATTEMPT = 'attempt-0123456789abcdef';

/** BroadcastChannel stand-in: what was posted and whether each end was closed. */
function fakeChannels() {
  const opened: {
    name: string;
    posted: unknown[];
    closed: boolean;
    deliver: (d: unknown) => void;
  }[] = [];
  const factory: ChannelFactory = (name) => {
    const end = {
      name,
      posted: [] as unknown[],
      closed: false,
      onmessage: null as ((event: MessageEvent) => void) | null,
      postMessage(data: unknown) {
        end.posted.push(data);
      },
      close() {
        end.closed = true;
      },
      deliver(data: unknown) {
        end.onmessage?.(new MessageEvent('message', { data }));
      },
    };
    opened.push(end);
    return end;
  };
  return { opened, factory };
}

function setLocation(path: string) {
  window.history.pushState({}, '', path);
}

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setLocation('/');
  vi.useRealTimers();
});

describe('the way back from /confirmed (lane B condition 2)', () => {
  it('keeps a path on this site', () => {
    expect(safeReturnTo('/admin/security?tab=sso#keys', ORIGIN)).toBe(
      '/admin/security?tab=sso#keys',
    );
    expect(safeReturnTo('/', ORIGIN)).toBe('/');
  });

  it.each([
    null,
    '',
    '//evil.example',
    'https://evil.example',
    '/\\evil.example',
    '/%2F%2Fevil.example',
    '%2F%2Fevil.example',
    '/%5Cevil.example',
    'javascript:alert(1)',
    '/a\nb',
    '/%0d%0aSet-Cookie:x',
    '/%E0%A4%A',
  ])('never leads off this site: %s', (value) => {
    expect(safeReturnTo(value, ORIGIN)).toBe('/');
  });
});

describe("the pop-up's answer (lane B condition 4)", () => {
  it('is read only in its exact shape, for this attempt', () => {
    const good = { type: 'supportx.reauth', attempt: ATTEMPT, status: 'ok' };
    expect(readConfirmedMessage(good, ATTEMPT)).toBe('confirmed');
    expect(readConfirmedMessage({ ...good, status: 'failed' }, ATTEMPT)).toBe('failed');
    expect(readConfirmedMessage({ ...good, status: 'unavailable' }, ATTEMPT)).toBe('unavailable');
    for (const bad of [
      { ...good, attempt: 'attempt-someone-elses-0000' },
      { ...good, status: 'confirmed' },
      { ...good, type: 'other' },
      { ...good, token: 'x' },
      { type: good.type, attempt: ATTEMPT },
      [good],
      'ok',
      null,
    ]) {
      expect(readConfirmedMessage(bad, ATTEMPT)).toBeNull();
    }
  });
});

describe('a confirmation in a pop-up', () => {
  function started(open: (url: string) => unknown = () => ({})) {
    const channels = fakeChannels();
    const redirect = vi.fn();
    const opened = vi.fn(open);
    const confirmation = startConfirmation({
      open: opened,
      redirect,
      channel: channels.factory,
      attemptId: () => ATTEMPT,
      here: () => '/admin/security',
      ttlMs: 1000,
    });
    return { confirmation, channels, redirect, opened };
  }

  it('opens /auth/confirm with this attempt and settles on its answer only', async () => {
    const { confirmation, channels, opened } = started();
    const url = new URL(String(opened.mock.calls[0]?.[0]), ORIGIN);
    expect(url.pathname).toBe('/api/v1/auth/confirm');
    expect(url.searchParams.get('attempt')).toBe(ATTEMPT);
    expect(url.searchParams.get('returnTo')).toBe('/admin/security');
    const channel = channels.opened[0];
    expect(channel?.name).toBe(REAUTH_CHANNEL);
    channel?.deliver({ type: 'supportx.reauth', attempt: 'attempt-another-tab-000', status: 'ok' });
    expect(channel?.closed).toBe(false); // another tab's answer: ignored
    channel?.deliver({ type: 'supportx.reauth', attempt: ATTEMPT, status: 'ok' });
    await expect(confirmation?.outcome).resolves.toBe('confirmed');
    expect(channel?.closed).toBe(true); // closed after the first match
  });

  it('Cancel and the time limit both end it as failed and close the channel', async () => {
    const cancelled = started();
    cancelled.confirmation?.cancel();
    await expect(cancelled.confirmation?.outcome).resolves.toBe('failed');
    expect(cancelled.channels.opened[0]?.closed).toBe(true);

    vi.useFakeTimers();
    const timed = started();
    vi.advanceTimersByTime(1000);
    await expect(timed.confirmation?.outcome).resolves.toBe('failed');
    expect(timed.channels.opened[0]?.closed).toBe(true);
  });

  it('a blocked pop-up confirms in the whole page instead, without an attempt id', () => {
    const { confirmation, redirect, channels } = started(() => null);
    expect(confirmation).toBeNull();
    const url = new URL(String(redirect.mock.calls[0]?.[0]), ORIGIN);
    expect(url.pathname).toBe('/api/v1/auth/confirm');
    expect(url.searchParams.has('attempt')).toBe(false);
    expect(channels.opened).toHaveLength(0);
  });
});

describe('REQ-SEC-027 AC1: a refused change goes ahead once the person confirms', () => {
  it('asks, opens the pop-up from the click, and sends the change again', async () => {
    let calls = 0;
    const fake = fakeApi({
      'POST /api/v1/api-keys': () => {
        calls += 1;
        return calls === 1
          ? { status: 403, body: problem(403, 'reauth_required') }
          : { status: 201, body: { id: 'k1' } };
      },
    });
    restore = fake.restore;
    const channels = fakeChannels();
    const open = vi.fn(() => ({}));
    renderUi(<ReauthDialog deps={{ open, channel: channels.factory, attemptId: () => ATTEMPT }} />);
    const made = call(api.POST('/api/v1/api-keys', { body: { name: 'CI' } as never }));
    fireEvent.click(await screen.findByTestId('reauth-confirm'));
    expect(open).toHaveBeenCalledTimes(1);
    expect(await screen.findByTestId('reauth-waiting')).toBeTruthy();
    act(() => {
      channels.opened[0]?.deliver({ type: 'supportx.reauth', attempt: ATTEMPT, status: 'ok' });
    });
    await expect(made).resolves.toEqual({ id: 'k1' });
    expect(fake.calls).toHaveLength(2);
    // Ready for the next one: a later refusal asks afresh (and opens a new pop-up from its click).
    calls = 0;
    const again = call(api.POST('/api/v1/api-keys', { body: { name: 'CI 2' } as never }));
    fireEvent.click(await screen.findByTestId('reauth-confirm'));
    expect(open).toHaveBeenCalledTimes(2);
    act(() => {
      channels.opened[1]?.deliver({ type: 'supportx.reauth', attempt: ATTEMPT, status: 'ok' });
    });
    await expect(again).resolves.toEqual({ id: 'k1' });
  });

  it('Cancel gives the refusal back, and nothing is sent again', async () => {
    const fake = fakeApi({
      'POST /api/v1/api-keys': { status: 403, body: problem(403, 'reauth_required') },
    });
    restore = fake.restore;
    renderUi(<ReauthDialog deps={{ open: () => ({}), channel: fakeChannels().factory }} />);
    const made = call(api.POST('/api/v1/api-keys', { body: { name: 'CI' } as never })).catch(
      (error: unknown) => error,
    );
    fireEvent.click(await screen.findByTestId('reauth-cancel'));
    expect(await made).toMatchObject({ status: 403 });
    expect(fake.calls).toHaveLength(1);
  });
});

describe('the /confirmed page', () => {
  it('from the pop-up: tells the opener only {type, attempt, status}, then closes', () => {
    setLocation(`/confirmed?status=ok&returnTo=%2Fadmin&attempt=${ATTEMPT}`);
    const channels = fakeChannels();
    const close = vi.fn();
    renderUi(<ConfirmedPage channel={channels.factory} close={close} replace={vi.fn()} />);
    expect(channels.opened[0]?.posted).toEqual([
      { type: 'supportx.reauth', attempt: ATTEMPT, status: 'ok' },
    ]);
    expect(channels.opened[0]?.closed).toBe(true);
    expect(close).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('confirmed-ok')).toBeTruthy();
  });

  it('after a whole-page confirmation: straight back to a path on this site', () => {
    setLocation('/confirmed?status=ok&returnTo=%2Fadmin%2Fsecurity');
    const replace = vi.fn();
    renderUi(<ConfirmedPage channel={fakeChannels().factory} close={vi.fn()} replace={replace} />);
    expect(replace).toHaveBeenCalledWith('/admin/security');
  });

  it('never links off the site, and an unknown status reads as failed', () => {
    setLocation('/confirmed?status=granted&returnTo=%2F%2Fevil.example');
    const replace = vi.fn();
    renderUi(<ConfirmedPage channel={fakeChannels().factory} close={vi.fn()} replace={replace} />);
    expect(screen.getByTestId('confirmed-failed')).toBeTruthy();
    expect(screen.getByTestId('confirmed-back').getAttribute('href')).toBe('/');
    expect(replace).not.toHaveBeenCalled();
  });
});
