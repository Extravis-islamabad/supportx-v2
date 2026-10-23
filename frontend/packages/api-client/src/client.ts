import createClient, { type Middleware } from 'openapi-fetch';

import { ApiError, asProblem } from './errors';
import type { paths } from './schema';

export const API_BASE = '/api/v1';
export const CSRF_HEADER = 'X-CSRF-Token';
export const REQUEST_ID_HEADER = 'X-Request-ID';
export const IDEMPOTENCY_HEADER = 'Idempotency-Key';
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const CONDITIONAL_METHODS = new Set(['PUT', 'PATCH', 'DELETE']);

/**
 * The session's CSRF token (synchronizer pattern). It comes from GET /auth/me and is held in
 * memory only, never in storage or a cookie; the session cookie itself is HttpOnly.
 */
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Latest ETag seen per resource path (GET or write response), sent back as If-Match. */
const etags = new Map<string, string>();

export function etagFor(path: string): string | undefined {
  return etags.get(path);
}

export function rememberEtag(path: string, etag: string | null): void {
  if (etag === null) etags.delete(path);
  else etags.set(path, etag);
}

/** Connectivity signal for the "Reconnecting…" banner: an outage, then the first success. */
export type Connectivity = 'online' | 'offline';
type Listener = (state: Connectivity) => void;
const listeners = new Set<Listener>();
let connectivity: Connectivity = 'online';

export function onConnectivity(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function currentConnectivity(): Connectivity {
  return connectivity;
}

export function reportConnectivity(state: Connectivity): void {
  if (state === connectivity) return;
  connectivity = state;
  listeners.forEach((listener) => {
    listener(state);
  });
}

function randomId(): string {
  return crypto.randomUUID();
}

/**
 * Everything every call needs, so screens never handle it:
 * - X-Request-ID on every request (the support reference when something fails);
 * - the CSRF header on state-changing methods;
 * - Idempotency-Key on POST unless the caller set one (a retried action must reuse its key);
 * - If-Match on PUT/PATCH/DELETE from the last ETag seen for that path, unless set explicitly;
 * - remembers ETags from responses.
 */
const conventions: Middleware = {
  onRequest({ request }) {
    if (!request.headers.has(REQUEST_ID_HEADER)) request.headers.set(REQUEST_ID_HEADER, randomId());
    request.headers.set('Accept', 'application/json');
    if (UNSAFE_METHODS.has(request.method) && csrfToken !== null) {
      request.headers.set(CSRF_HEADER, csrfToken);
    }
    if (request.method === 'POST' && !request.headers.has(IDEMPOTENCY_HEADER)) {
      request.headers.set(IDEMPOTENCY_HEADER, randomId());
    }
    if (CONDITIONAL_METHODS.has(request.method) && !request.headers.has('If-Match')) {
      const etag = etags.get(new URL(request.url).pathname);
      if (etag !== undefined) request.headers.set('If-Match', etag);
    }
    return request;
  },
  onResponse({ request, response }) {
    const etag = response.headers.get('ETag');
    if (response.ok && etag !== null) rememberEtag(new URL(request.url).pathname, etag);
    reportConnectivity([502, 503, 504].includes(response.status) ? 'offline' : 'online');
    return response;
  },
};

/**
 * Typed client for the SupportX API: paths, parameters and bodies come from the generated
 * schema.ts (D-022), so a backend contract change breaks `tsc` where the UI uses it.
 * Same-origin cookies only (the BFF session, D-009).
 */
export const api = createClient<paths>({
  baseUrl: typeof window === 'undefined' ? '' : window.location.origin,
  credentials: 'same-origin',
  // Resolved per call (not captured at import) so tests can stub fetch.
  fetch: (request: Request) => globalThis.fetch(request),
});
api.use(conventions);

interface Result<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/**
 * Await an openapi-fetch call and return its data, or throw a typed ApiError: problem details
 * parsed, request ID attached, network failures reported as `kind: 'network'`.
 */
export async function call<T>(promise: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await promise;
  } catch (cause) {
    if (cause instanceof ApiError) throw cause;
    reportConnectivity('offline');
    throw new ApiError(0, null, null, 'network');
  }
  const { response } = result;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      asProblem(result.error),
      response.headers.get(REQUEST_ID_HEADER),
    );
  }
  return result.data as T;
}

export type App = 'console' | 'portal';

/** Where to send the browser to log in, coming back to `returnTo` (same-origin path). */
export function loginUrl(app: App, returnTo: string): string {
  const params = new URLSearchParams({ app, returnTo });
  return `${API_BASE}/auth/login?${params.toString()}`;
}
