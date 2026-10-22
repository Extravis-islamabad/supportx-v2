import { vi } from 'vitest';

import type { MeResponse } from '@supportx/api-client';

/** A session as GET /api/v1/auth/me returns it (typed by the generated schema). */
export function session(overrides: Partial<MeResponse['user']> = {}): MeResponse {
  return {
    user: {
      id: '01900000-0000-7000-8000-000000000101',
      email: 'tech@demo.test',
      display_name: 'Tariq Technician',
      locale: 'en',
      user_type: 'technician',
      roles: ['technician'],
      ...overrides,
    },
    tenant: { id: '01900000-0000-7000-8000-00000000de30', name: 'Demo Company' },
    tenants: [{ id: '01900000-0000-7000-8000-00000000de30', name: 'Demo Company' }],
    csrf_token: 'csrf-from-session',
  };
}

export interface Call {
  url: string;
  method: string;
  headers: Headers;
}

/** Stub fetch: /auth/me answers with `me` (or 401 when null); everything else 200 or 204. */
export function stubApi(me: MeResponse | null) {
  const calls: Call[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : input.toString();
    calls.push({ url, method: init?.method ?? 'GET', headers: new Headers(init?.headers) });
    if (url.endsWith('/auth/me')) {
      return Promise.resolve(
        me === null
          ? new Response(JSON.stringify({ code: 'unauthenticated' }), { status: 401 })
          : new Response(JSON.stringify(me), { status: 200 }),
      );
    }
    if (url.endsWith('/auth/logout')) {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(new Response('{}', { status: 200 }));
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}
