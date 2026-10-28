import { useCallback, useMemo, useState } from 'react';

import { ApiError } from '@supportx/api-client';

import { markHandled, reportError } from './reporter';

export interface FormProblemState {
  /** The refusal shown at the form, if any. */
  error: ApiError | null;
  /**
   * Show a failed save: an expected refusal (a rule, a validation, a limit) at the form, once;
   * anything else (an outage, a server error) as the app's error toast. True when shown here.
   */
  show: (error: unknown) => boolean;
  clear: () => void;
}

/** State for <FormProblem>: one per form (QA WP-029 BUG-02). */
export function useFormProblem(): FormProblemState {
  const [error, setError] = useState<ApiError | null>(null);
  const show = useCallback((next: unknown) => {
    if (next instanceof ApiError && next.isRefusal && !next.isConflict) {
      markHandled(next);
      setError(next);
      return true;
    }
    reportError(next);
    return false;
  }, []);
  const clear = useCallback(() => {
    setError(null);
  }, []);
  return useMemo(() => ({ error, show, clear }), [error, show, clear]);
}
