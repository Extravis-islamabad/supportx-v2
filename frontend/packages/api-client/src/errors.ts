import type { components } from './schema';

/** RFC 9457 problem details as the API returns them (generated type). */
export type ProblemDetail = components['schemas']['ProblemDetail'];
export type FieldError = components['schemas']['FieldError'];

/** network = no answer at all; server = 5xx; client = 4xx with (usually) a problem body. */
export type ApiErrorKind = 'network' | 'server' | 'client';

/** Problem codes the UI explains with a dedicated, translated message (WP-009 entitlements). */
export const ENTITLEMENT_CODES = new Set([
  'entitlement_required',
  'read_only_mode',
  'technician_limit_reached',
  'limit_reached',
]);

/**
 * Every failed API call, typed. Screens never show `message` (an internal code): they render
 * `messageKey` through the labels package and offer `requestId` as the support reference.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly problem: ProblemDetail | null;
  /** X-Request-ID of the failed call: shown as "Copy reference" for support. */
  readonly requestId: string | null;

  constructor(
    status: number,
    problem: ProblemDetail | null,
    requestId: string | null,
    kind?: ApiErrorKind,
  ) {
    super(problem?.code ?? (status === 0 ? 'network_error' : `http_${String(status)}`));
    this.name = 'ApiError';
    this.status = status;
    this.problem = problem;
    this.requestId = problem?.request_id ?? requestId;
    this.kind = kind ?? (status === 0 ? 'network' : status >= 500 ? 'server' : 'client');
  }

  /** Machine code (`version_conflict`, `read_only_mode` ...). */
  get code(): string {
    if (this.problem !== null) return this.problem.code;
    return this.kind === 'network'
      ? 'network_error'
      : this.kind === 'server'
        ? 'internal_error'
        : 'bad_request';
  }

  /** Labels key for the human message, e.g. `errors.session_expired`. */
  get messageKey(): string {
    return this.problem?.message_key ?? `errors.${this.code}`;
  }

  get params(): NonNullable<ProblemDetail['params']> {
    return this.problem?.params ?? {};
  }

  /** Field-level errors (validation), each with a dotted field path like `body.signature`. */
  get fieldErrors(): FieldError[] {
    return this.problem?.errors ?? [];
  }

  get isConflict(): boolean {
    return this.status === 409 && this.code === 'version_conflict';
  }

  get isEntitlement(): boolean {
    return ENTITLEMENT_CODES.has(this.code);
  }

  /** The service is (temporarily) unreachable: no answer, or a gateway/availability error. */
  get isOutage(): boolean {
    return this.kind === 'network' || [502, 503, 504].includes(this.status);
  }
}

/** Parse a problem body if there is one (a proxy error page is not JSON). */
export function asProblem(body: unknown): ProblemDetail | null {
  if (typeof body === 'object' && body !== null && 'code' in body && 'message_key' in body) {
    return body as ProblemDetail;
  }
  return null;
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}
