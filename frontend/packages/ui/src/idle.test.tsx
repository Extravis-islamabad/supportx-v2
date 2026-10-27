import { act, fireEvent, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeApi, fakeSession } from '@supportx/api-client/testing';

import { IdleWatcher } from './IdleWatcher';
import { renderUi } from './test/render';

// WP-039 session 3 (REQ-SEC-029 AC1): warned 2 minutes ahead, signed out at the limit.

let restore: () => void = () => undefined;
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  restore();
});

function stack() {
  const fake = fakeApi({
    'GET /api/v1/auth/me': { body: fakeSession() },
    'POST /api/v1/auth/logout': { status: 204 },
  });
  restore = fake.restore;
  return fake;
}

async function wait(seconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(seconds * 1000);
  });
}

describe('idle timeout', () => {
  it('warns two minutes ahead with a countdown; staying keeps the session', async () => {
    const fake = stack();
    renderUi(<IdleWatcher idleSeconds={30 * 60} />);
    await wait(27 * 60); // 27 minutes without activity: nothing yet
    expect(screen.queryByTestId('idle-stay')).toBeNull();
    await wait(2 * 60 + 5); // 29 minutes 5 seconds
    expect(await screen.findByText(/You will be signed out in 0:5\d/)).toBeDefined();
    const before = fake.find('GET', '/api/v1/auth/me').length;
    fireEvent.click(screen.getByTestId('idle-stay'));
    await wait(1);
    expect(fake.find('GET', '/api/v1/auth/me').length).toBe(before + 1); // told the server
    expect(fake.find('POST', '/api/v1/auth/logout')).toHaveLength(0);
  });

  it('signs out at the limit when nobody answers', async () => {
    const fake = stack();
    renderUi(<IdleWatcher idleSeconds={30 * 60} />);
    await wait(30 * 60 + 2);
    expect(fake.find('POST', '/api/v1/auth/logout')).toHaveLength(1);
  });

  it('activity resets the clock', async () => {
    const fake = stack();
    renderUi(<IdleWatcher idleSeconds={30 * 60} />);
    await wait(20 * 60);
    fireEvent.keyDown(window, { key: 'a' });
    await wait(20 * 60); // 40 minutes in all, but only 20 since the last key
    expect(fake.find('POST', '/api/v1/auth/logout')).toHaveLength(0);
    expect(screen.queryByTestId('idle-stay')).toBeNull();
  });
});
