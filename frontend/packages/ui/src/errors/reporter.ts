import { MutationCache, QueryCache, QueryClient, type Query } from '@tanstack/react-query';

import { ApiError } from '@supportx/api-client';

/** Who shows errors to the user; set by <ErrorReporterProvider> once the app has mounted. */
export type ErrorReporter = (error: unknown) => void;
let reporter: ErrorReporter | null = null;

export function setErrorReporter(next: ErrorReporter | null): void {
  reporter = next;
}

export function reportError(error: unknown): void {
  reporter?.(error);
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
        reportError(error);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (!isSilent(mutation.meta)) reportError(error);
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  });
}
