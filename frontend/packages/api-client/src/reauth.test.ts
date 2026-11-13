import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, call, setCsrfToken, setReauthConfirmer } from './client';
import { ApiError } from './errors';
import { fakeApi, problem } from './testing';

// REQ-SEC-027 (WP-057 S2a): a sensitive action refused with 403 reauth_required is confirmed in
// the pop-up and sent again once, with the same Idempotency-Key; anything else reaches the caller.
const KEYS = '/api/v1/api-keys';
const BODY = { name: 'CI', scopes: ['incidents.read'], expires_in_days: 30 };

describe('a refused sensitive action', () => {
  let restore: () => void = () => undefined;
  afterEach(() => {
    restore();
    setReauthConfirmer(null);
    setCsrfToken(null);
  });

  function refusedOnce() {
    let calls = 0;
    const fake = fakeApi({
      [`POST ${KEYS}`]: () => {
        calls += 1;
        return calls === 1
          ? {
              status: 403,
              body: problem(403, 'reauth_required', { params: { max_age_minutes: 10 } }),
            }
          : { status: 201, body: { id: 'k1' } };
      },
    });
    restore = fake.restore;
    return fake;
  }

  it('is sent again once after the person confirms, with the same idempotency key', async () => {
    const fake = refusedOnce();
    const confirmer = vi.fn(() => Promise.resolve('confirmed' as const));
    setReauthConfirmer(confirmer);
    setCsrfToken('csrf-1');
    const made = await call(api.POST(KEYS, { body: BODY as never }));
    expect(made).toEqual({ id: 'k1' });
    expect(confirmer).toHaveBeenCalledTimes(1);
    const [first, second] = fake.calls;
    expect(fake.calls).toHaveLength(2);
    expect(second?.headers.get('Idempotency-Key')).toBe(first?.headers.get('Idempotency-Key'));
    expect(second?.headers.get('X-SupportX-Confirmed-Retry')).toBe('1');
    expect(second?.body).toEqual(first?.body);
  });

  it('reaches the caller as the refusal when the person does not confirm', async () => {
    const fake = refusedOnce();
    setReauthConfirmer(() => Promise.resolve('failed'));
    const error = await call(api.POST(KEYS, { body: BODY as never })).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(403);
    expect(fake.calls).toHaveLength(1); // never sent again
  });

  it('asks only once for several refused calls at the same time', async () => {
    let calls = 0;
    const fake = fakeApi({
      [`POST ${KEYS}`]: () => {
        calls += 1;
        return calls <= 2
          ? { status: 403, body: problem(403, 'reauth_required') }
          : { status: 201, body: { id: `k${String(calls)}` } };
      },
    });
    restore = fake.restore;
    let finish: (outcome: 'confirmed') => void = () => undefined;
    const confirmer = vi.fn(
      () =>
        new Promise<'confirmed'>((resolve) => {
          finish = resolve;
        }),
    );
    setReauthConfirmer(confirmer);
    const both = Promise.all([
      call(api.POST(KEYS, { body: BODY as never })),
      call(api.POST(KEYS, { body: BODY as never })),
    ]);
    await vi.waitFor(() => {
      expect(fake.calls).toHaveLength(2);
    });
    finish('confirmed');
    await both;
    expect(confirmer).toHaveBeenCalledTimes(1);
  });

  it('without a confirmer (the mobile app) the refusal goes straight to the caller', async () => {
    const fake = refusedOnce();
    const error = await call(api.POST(KEYS, { body: BODY as never })).catch((e: unknown) => e);
    expect((error as ApiError).status).toBe(403);
    expect(fake.calls).toHaveLength(1);
  });
});
