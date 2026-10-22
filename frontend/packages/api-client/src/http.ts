import type { components } from './schema';

/** RFC 9457 problem details as the API returns them (generated type). */
export type ProblemDetail = components['schemas']['ProblemDetail'];

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
export const CSRF_HEADER = 'X-CSRF-Token';
export const API_BASE = '/api/v1';

/**
 * The session's CSRF token (synchronizer pattern). It comes from GET /auth/me and is held in
 * memory only, never in storage or a cookie; the session cookie itself is HttpOnly.
 */
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** An API call that ended in an error status; `problem` carries the machine code for labels. */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetail | null;

  constructor(status: number, problem: ProblemDetail | null) {
    super(problem?.code ?? `http_${String(status)}`);
    this.name = 'ApiError';
    this.status = status;
    this.problem = problem;
  }

  /** Labels key for this error, e.g. `errors.session_expired` (never raw text). */
  get messageKey(): string {
    return this.problem?.message_key ?? 'errors.internal_error';
  }
}

async function readProblem(response: Response): Promise<ProblemDetail | null> {
  try {
    return (await response.json()) as ProblemDetail;
  } catch {
    return null; // not JSON (e.g. a proxy error page): the status alone must do
  }
}

export type App = 'console' | 'portal';

/** Where to send the browser to log in, coming back to `returnTo` (same-origin path). */
export function loginUrl(app: App, returnTo: string): string {
  const params = new URLSearchParams({ app, returnTo });
  return `${API_BASE}/auth/login?${params.toString()}`;
}

/**
 * fetch() for the SupportX API: same-origin cookies, JSON, the CSRF header on every
 * state-changing method, and RFC 9457 errors raised as ApiError.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (UNSAFE_METHODS.has(method) && csrfToken !== null) {
    headers.set(CSRF_HEADER, csrfToken);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: 'same-origin',
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readProblem(response));
  }
  return response;
}

/** GET and parse JSON. */
export async function apiGet<T>(path: string): Promise<T> {
  return (await (await apiFetch(path)).json()) as T;
}

/** POST a JSON body (CSRF header added automatically). */
export async function apiPost<T>(path: string, body?: unknown): Promise<T | null> {
  const response = await apiFetch(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return response.status === 204 ? null : ((await response.json()) as T);
}
