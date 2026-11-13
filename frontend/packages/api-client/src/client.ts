import createClient, { type Middleware } from 'openapi-fetch';

import { ApiError, asProblem } from './errors';
import type { paths } from './schema';

export const API_BASE = '/api/v1';
export const CSRF_HEADER = 'X-CSRF-Token';
export const REQUEST_ID_HEADER = 'X-Request-ID';
export const IDEMPOTENCY_HEADER = 'Idempotency-Key';
/** Which app made the call: the field history records "UI" for these, "API" for the rest. */
export const CLIENT_HEADER = 'X-SupportX-Client';
/** The user's time zone (IANA): "today" and "this week" in filters are the user's (WP-012). */
export const TIME_ZONE_HEADER = 'X-Time-Zone';
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

/** The CSRF token for requests made outside openapi-fetch (file uploads with progress). */
export function currentCsrfToken(): string | null {
  return csrfToken;
}

/**
 * The mobile app's session ID (ADR-044), sent in a header instead of a cookie. The web apps never
 * set it: their session stays in the HttpOnly cookie, out of JavaScript's reach.
 */
export const SESSION_HEADER = 'X-SupportX-Session';
let sessionId: string | null = null;
type SessionListener = (id: string | null) => void;
const sessionListeners = new Set<SessionListener>();

export function setSessionId(id: string | null): void {
  sessionId = id;
}

export function currentSessionId(): string | null {
  return sessionId;
}

/** Told when the server hands out a new session ID (a tenant switch), so the app can keep it. */
export function onSessionId(listener: SessionListener): () => void {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

/** The app making calls (console / portal / mobile), for requests made outside openapi-fetch. */
export function currentClientApp(): ClientApp | null {
  return clientApp;
}

let clientApp: ClientApp | null = null;
let preferredTimeZone: string | null = null;

/** Set once by the app shell (SessionGate): every call then says which app it comes from. */
export function setClientApp(app: ClientApp | null): void {
  clientApp = app;
}

/** The user's profile time zone; null falls back to the browser's. */
export function setPreferredTimeZone(zone: string | null): void {
  preferredTimeZone = zone;
}

/** The zone sent with every call (profile preference, else the browser's, else none). */
export function currentTimeZone(): string | undefined {
  if (preferredTimeZone !== null && preferredTimeZone !== '') return preferredTimeZone;
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
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

/** How a confirmation ended (REQ-SEC-027): the pop-up's answer. */
export type ReauthOutcome = 'confirmed' | 'failed' | 'unavailable';

// Set by the web apps (packages/ui): opens the confirm pop-up. Never set in the mobile app, which
// cannot confirm and is refused `interactive_session_required` instead.
let reauthConfirmer: (() => Promise<ReauthOutcome>) | null = null;
let pendingConfirmation: Promise<ReauthOutcome> | null = null;
// A copy of each state-changing request, kept until its answer: a refused action is sent again
// once after the person confirmed (the body can be read only once).
const originals = new WeakMap<Request, Request>();
const RETRIED_HEADER = 'X-SupportX-Confirmed-Retry';

/** The web apps' confirm pop-up (REQ-SEC-027); null to stop confirming (tests). */
export function setReauthConfirmer(confirmer: (() => Promise<ReauthOutcome>) | null): void {
  reauthConfirmer = confirmer;
}

/** One confirmation at a time: several refused calls share the same pop-up. */
function confirmOnce(confirmer: () => Promise<ReauthOutcome>): Promise<ReauthOutcome> {
  pendingConfirmation ??= confirmer().finally(() => {
    pendingConfirmation = null;
  });
  return pendingConfirmation;
}

async function reauthRequired(response: Response): Promise<boolean> {
  if (response.status !== 403) return false;
  try {
    const body = (await response.clone().json()) as { code?: unknown };
    return body.code === 'reauth_required';
  } catch {
    return false;
  }
}

/**
 * Everything every call needs, so screens never handle it:
 * - X-Request-ID on every request (the support reference when something fails);
 * - X-SupportX-Client (console / portal) and X-Time-Zone on every request;
 * - the CSRF header on state-changing methods;
 * - Idempotency-Key on POST unless the caller set one (a retried action must reuse its key);
 * - If-Match on PUT/PATCH/DELETE from the last ETag seen for that path, unless set explicitly;
 * - remembers ETags from responses.
 */
const conventions: Middleware = {
  onRequest({ request }) {
    if (!request.headers.has(REQUEST_ID_HEADER)) request.headers.set(REQUEST_ID_HEADER, randomId());
    request.headers.set('Accept', 'application/json');
    if (clientApp !== null) request.headers.set(CLIENT_HEADER, clientApp);
    if (sessionId !== null) request.headers.set(SESSION_HEADER, sessionId);
    const zone = currentTimeZone();
    if (zone !== undefined && !request.headers.has(TIME_ZONE_HEADER)) {
      request.headers.set(TIME_ZONE_HEADER, zone);
    }
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
    if (reauthConfirmer !== null && UNSAFE_METHODS.has(request.method)) {
      originals.set(request, request.clone());
    }
    return request;
  },
  async onResponse({ request, response }) {
    // A sensitive action refused for want of a recent confirmation (REQ-SEC-027): confirm in
    // the pop-up, then send the very same request again, once. Its Idempotency-Key is the same;
    // the refusal came before anything was done or stored. Any other answer goes to the caller.
    const original = originals.get(request);
    originals.delete(request);
    if (
      original !== undefined &&
      reauthConfirmer !== null &&
      !request.headers.has(RETRIED_HEADER) &&
      (await reauthRequired(response))
    ) {
      const outcome = await confirmOnce(reauthConfirmer);
      if (outcome === 'confirmed') {
        original.headers.set(RETRIED_HEADER, '1');
        if (csrfToken !== null) original.headers.set(CSRF_HEADER, csrfToken);
        const again = await globalThis.fetch(original);
        observe(original, again);
        return again;
      }
    }
    observe(request, response);
    // Nothing returned: the response is only read here. Returning it makes openapi-fetch check
    // `instanceof Response`, which fails for Expo's native fetch (its FetchResponse does not
    // extend the global Response), so every call from the mobile app threw after a 200.
    return undefined;
  },
};

/** What every answer tells the client: its ETag, connectivity, and a renewed session. */
function observe(request: Request, response: Response): void {
  const etag = response.headers.get('ETag');
  if (response.ok && etag !== null) rememberEtag(new URL(request.url).pathname, etag);
  reportConnectivity([502, 503, 504].includes(response.status) ? 'offline' : 'online');
  const renewed = response.headers.get(SESSION_HEADER);
  if (response.ok && sessionId !== null && renewed !== null && renewed !== sessionId) {
    sessionId = renewed; // a tenant switch issues a new session (ADR-044)
    sessionListeners.forEach((listener) => {
      listener(renewed);
    });
  }
}

/**
 * The page's own origin in a browser; '' where there is no page location (React Native defines
 * `window` but not `window.location`).
 */
function pageOrigin(): string {
  const { location } = globalThis as { location?: { origin?: string } };
  return location?.origin ?? '';
}

function createApi(baseUrl: string) {
  const client = createClient<paths>({
    baseUrl,
    credentials: 'same-origin',
    // Resolved per call (not captured at import) so tests can stub fetch.
    fetch: (request: Request) => globalThis.fetch(request),
  });
  client.use(conventions);
  return client;
}

let apiOrigin: string | null = null;

/**
 * Typed client for the SupportX API: paths, parameters and bodies come from the generated
 * schema.ts (D-022), so a backend contract change breaks `tsc` where the UI uses it.
 * The web apps call their own origin with same-origin cookies (the BFF session, D-009).
 * `let`, not `const`: an ES live binding, so setApiOrigin() reaches every module importing it.
 */
export let api = createApi(pageOrigin());

/**
 * The server the native app talks to, chosen at run time on its server-address screen
 * (docs/architecture/mobile.md). null returns to the page's origin. The web apps never call it.
 */
export function setApiOrigin(origin: string | null): void {
  apiOrigin = origin === null ? null : origin.replace(/\/+$/, '');
  api = createApi(apiOrigin ?? pageOrigin());
}

export function currentApiOrigin(): string | null {
  return apiOrigin;
}

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
/** Who makes the calls (X-SupportX-Client): a web app, or the native app (D-159). */
export type ClientApp = App | 'mobile';

/** Where to send the browser to log in, coming back to `returnTo` (same-origin path). */
export function loginUrl(app: App, returnTo: string): string {
  const params = new URLSearchParams({ app, returnTo });
  return `${API_BASE}/auth/login?${params.toString()}`;
}

/**
 * Where to confirm who you are (REQ-SEC-027): Keycloak asks again, then the browser lands on the
 * UI's /confirmed page with the result, `returnTo` and, from a pop-up, the opener's `attempt` id.
 */
export function confirmUrl(returnTo: string, attempt?: string): string {
  const params = new URLSearchParams({ returnTo });
  if (attempt !== undefined) params.set('attempt', attempt);
  return `${API_BASE}/auth/confirm?${params.toString()}`;
}
