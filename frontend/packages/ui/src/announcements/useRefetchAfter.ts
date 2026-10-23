import { useEffect, useLayoutEffect, useRef } from 'react';

/** Browsers cap timers at ~24.8 days; we re-check daily anyway (the server answers again). */
const MAX_DELAY_MS = 24 * 60 * 60 * 1000;
/** A little after the moment, so the server's clock has surely passed it too. */
const GRACE_MS = 750;

/**
 * Run `refetch` once `seconds` after the data was fetched (`fetchedAt`, ms). For screens whose
 * content changes by the clock alone (a publish window starting or ending): the server says
 * when, relative to its own clock, so the user's clock does not need to be right.
 * `seconds` null/undefined: nothing scheduled.
 */
export function useRefetchAfter(
  seconds: number | null | undefined,
  fetchedAt: number,
  refetch: () => void,
): void {
  const latest = useRef(refetch);
  useLayoutEffect(() => {
    latest.current = refetch;
  });
  useEffect(() => {
    if (seconds === null || seconds === undefined) return;
    const due = fetchedAt + seconds * 1000 + GRACE_MS;
    const delay = Math.min(Math.max(due - Date.now(), 0), MAX_DELAY_MS);
    const timer = setTimeout(() => {
      latest.current();
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [seconds, fetchedAt]);
}
