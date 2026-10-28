import { useState } from 'react';

import { ApiError } from '@supportx/api-client';

import { markHandled } from './reporter';

/** The 409 an editor shows in its <ConflictDialog> (CLAUDE.md rule g; QA WP-029 BUG-05). */
export interface ConflictState {
  /** The 409 itself (null: no conflict). */
  error: unknown;
  open: boolean;
  /** Keep a version conflict for the dialog (never a toast); false for any other error. */
  take: (error: unknown) => boolean;
  clear: () => void;
  /** The version saved now, from the 409: "Keep my changes" saves on top of it. */
  latestVersion: number | undefined;
}

export function useConflict(): ConflictState {
  const [error, setError] = useState<unknown>(null);
  const current = error instanceof ApiError ? error.params.current_version : undefined;
  return {
    error,
    open: error !== null,
    take: (next) => {
      if (!(next instanceof ApiError) || !next.isConflict) return false;
      markHandled(next);
      setError(next);
      return true;
    },
    clear: () => {
      setError(null);
    },
    latestVersion: typeof current === 'number' ? current : undefined,
  };
}

/** The props of a <ConflictDialog> for a one-step change (a switch, a move, a removal). */
export interface ConflictRetry {
  /** Keep a version conflict for the dialog, with how to make the change again; else false. */
  take: (error: unknown, again: (version: number) => void) => boolean;
  dialog: { open: boolean; error: unknown; onReload: () => void; onKeepMine: () => void };
}

/**
 * A one-step change someone else beat (409): the shared dialog says who, when and what;
 * "Reload" leaves the change unmade, "Keep my changes" makes it again on the saved version.
 */
export function useConflictRetry(): ConflictRetry {
  const conflict = useConflict();
  const [again, setAgain] = useState<(version: number) => void>();
  return {
    take: (error, retry) => {
      if (!conflict.take(error)) return false;
      setAgain(() => retry);
      return true;
    },
    dialog: {
      open: conflict.open,
      error: conflict.error,
      onReload: () => {
        conflict.clear();
        setAgain(undefined);
      },
      onKeepMine: () => {
        conflict.clear();
        if (again !== undefined && conflict.latestVersion !== undefined) {
          again(conflict.latestVersion);
        }
        setAgain(undefined);
      },
    },
  };
}
