import { afterEach, describe, expect, it } from 'vitest';

import { api, call, currentConnectivity, onConnectivity, setCsrfToken } from './client';
import { ApiError } from './errors';
import { fakeApi, fakeUser, problem } from './testing';

const USER = '/api/v1/users/01900000-0000-7000-8000-000000000101';

describe('client conventions', () => {
  let restore: () => void = () => undefined;
  afterEach(() => {
    restore();
    setCsrfToken(null);
  });

  it('sends a request ID on every call, CSRF and an idempotency key on POST', async () => {
    const fake = fakeApi({
      'GET /api/v1/health': { body: { status: 'ok', version: '1' } },
      'POST /api/v1/auth/logout': { status: 204 },
    });
    restore = fake.restore;
    setCsrfToken('csrf-1');

    await call(api.GET('/api/v1/health'));
    await call(api.POST('/api/v1/auth/logout'));

    const [get, post] = fake.calls;
    expect(get?.headers.get('X-Request-ID')).toMatch(/^[0-9a-f-]{36}$/);
    expect(get?.headers.has('X-CSRF-Token')).toBe(false);
    expect(get?.headers.has('Idempotency-Key')).toBe(false);
    expect(post?.headers.get('X-CSRF-Token')).toBe('csrf-1');
    expect(post?.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(post?.headers.get('X-Request-ID')).not.toBe(get?.headers.get('X-Request-ID'));
  });

  it('sends the last ETag it saw for a record as If-Match on a write', async () => {
    const fake = fakeApi({
      [`GET ${USER}`]: { body: fakeUser(), headers: { ETag: '"3"' } },
      [`PATCH ${USER}`]: { body: fakeUser({ version: 4 }), headers: { ETag: '"4"' } },
    });
    restore = fake.restore;
    const path = { params: { path: { user_id: fakeUser().id } } };

    await call(api.GET('/api/v1/users/{user_id}', path));
    // No explicit If-Match: the client fills in the remembered ETag.
    await call(
      api.PATCH('/api/v1/users/{user_id}', {
        ...path,
        params: { ...path.params, header: {} as { 'If-Match': string } },
        body: { signature: 'x' },
      }),
    );
    await call(
      api.PATCH('/api/v1/users/{user_id}', {
        params: { ...path.params, header: { 'If-Match': '"9"' } },
        body: { signature: 'y' },
      }),
    );

    expect(fake.find('PATCH', USER).map((c) => c.headers.get('If-Match'))).toEqual(['"3"', '"9"']);
  });

  it('turns problem details into a typed ApiError', async () => {
    const fake = fakeApi({
      [`PATCH ${USER}`]: {
        status: 422,
        body: problem(422, 'validation_failed', {
          errors: [
            {
              field: 'body.time_zone',
              code: 'invalid_choice',
              message_key: 'errors.field.invalid_choice',
              params: {},
            },
          ],
        }),
      },
    });
    restore = fake.restore;

    const error = await call(
      api.PATCH('/api/v1/users/{user_id}', {
        params: { path: { user_id: fakeUser().id }, header: { 'If-Match': '"1"' } },
        body: { time_zone: 'Mars/Base' },
      }),
    ).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(422);
    expect(apiError.code).toBe('validation_failed');
    expect(apiError.messageKey).toBe('errors.validation_failed');
    expect(apiError.requestId).toBe('req-0001');
    expect(apiError.fieldErrors.map((e) => e.field)).toEqual(['body.time_zone']);
    expect(apiError.isConflict).toBe(false);
  });

  it('marks 409 version_conflict and the entitlement codes', () => {
    expect(new ApiError(409, problem(409, 'version_conflict'), null).isConflict).toBe(true);
    for (const code of ['entitlement_required', 'read_only_mode', 'technician_limit_reached']) {
      expect(new ApiError(403, problem(403, code), null).isEntitlement).toBe(true);
    }
    expect(new ApiError(403, problem(403, 'permission_denied'), null).isEntitlement).toBe(false);
  });

  it('reports a network failure as an outage and recovers on the next success', async () => {
    let down = true;
    const fake = fakeApi({
      'GET /api/v1/health': () =>
        down ? 'network-error' : { body: { status: 'ok', version: '1' } },
    });
    restore = fake.restore;
    const seen: string[] = [];
    const stop = onConnectivity((state) => seen.push(state));

    const error = (await call(api.GET('/api/v1/health')).catch((e: unknown) => e)) as ApiError;
    expect(error.kind).toBe('network');
    expect(error.isOutage).toBe(true);
    expect(error.messageKey).toBe('errors.network_error');
    expect(currentConnectivity()).toBe('offline');

    down = false;
    await call(api.GET('/api/v1/health'));
    expect(seen).toEqual(['offline', 'online']);
    stop();
  });

  it('treats a non-JSON 502 from a proxy as a server outage with a generic message', async () => {
    const fake = fakeApi({ 'GET /api/v1/health': { status: 502 } });
    restore = fake.restore;
    const error = (await call(api.GET('/api/v1/health')).catch((e: unknown) => e)) as ApiError;
    expect([error.kind, error.code, error.isOutage]).toEqual(['server', 'internal_error', true]);
    await call(api.GET('/api/v1/health')).catch(() => undefined);
  });
});
