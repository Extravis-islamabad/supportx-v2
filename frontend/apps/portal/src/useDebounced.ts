import { useEffect, useState } from 'react';

/** How long typing pauses before a search goes to the server. */
export const SEARCH_DELAY_MS = 300;

/** `value`, once it has stopped changing for `delay` ms (search boxes). */
export function useDebounced<T>(value: T, delay: number = SEARCH_DELAY_MS): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return debounced;
}
