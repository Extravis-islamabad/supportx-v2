import { MutationCache, QueryCache, QueryClient, type Query } from '@tanstack/react-query';

import { ApiError } from '@supportx/api-client';

/** Who shows errors to the user; set by <ErrorReporterProvider> once the app has mounted. */
export type ErrorReporter = (error: unknown) => void;
let reporter: ErrorReporter | null = null;

export function setErrorReporter(next: ErrorReporter | null): void {
  reporter = next;
}

// Errors already on screen: reported (a toast) or shown by the screen itself (at its form).
// Each error is shown once, however many places report it (QA WP-029 BUG-02).
const shown = new WeakSet<object>();

function isObject(error: unknown): error is object {
  return typeof error === 'object' && error !== null;
}

/** Show an error to the user, once (a second report of the same error is ignored). */
export function reportError(error: unknown): void {
  if (isObject(error)) {
    if (shown.has(error)) return;
    shown.add(error);
  }
  reporter?.(error);
}

/** The screen shows this error itself (at its form): the app-wide reporter stays quiet. */
export function markHandled(error: unknown): void {
  if (isObject(error)) shown.add(error);
}

/**
 * The cache reports a failed call after the screen's own handlers ran: TanStack calls the cache's
 * onError before the screen's `mutate(..., { onError })`, so reporting at once would show a
 * refusal the form is about to show at the field (twice, as a toast too).
 */
function reportLater(error: unknown): void {
  setTimeout(() => {
    reportError(error);
  }, 0);
}

/**
 * Query/mutation meta flags:
 * - `silent`: the screen handles this error itself (session check, inline form errors,
 *   the conflict dialog), so no global toast.
 */
export interface ErrorMeta extends Record<string, unknown> {
  silent?: boolean;
}

function isSilent(meta: Record<string, unknown> | undefined): boolean {
  return meta?.silent === true;
}

/** Outages are worth retrying; a 4xx answer will not change by asking again. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  return error instanceof ApiError && error.isOutage && failureCount < 3;
}

/**
 * The app's QueryClient: every failed query or mutation is reported once (translated toast)
 * unless marked `meta: { silent: true }`. Background refetch failures of data already on screen
 * are not repeated: the connectivity banner covers outages.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query: Query<unknown, unknown, unknown>) => {
        if (isSilent(query.meta)) return;
        if (query.state.data !== undefined && error instanceof ApiError && error.isOutage) return;
        reportLater(error);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (!isSilent(mutation.meta)) reportLater(error);
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  });
}
