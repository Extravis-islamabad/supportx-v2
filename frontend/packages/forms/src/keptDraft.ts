import { useEffect, useRef, useState } from 'react';
import type { FieldValues, UseFormReturn } from 'react-hook-form';

const PREFIX = 'supportx.draft.';
const SAVE_AFTER_MS = 400;

function read(key: string): unknown {
  try {
    const raw = window.sessionStorage.getItem(PREFIX + key);
    return raw === null ? null : (JSON.parse(raw) as unknown);
  } catch {
    return null; // storage blocked (private mode) or an old, unreadable value: nothing kept
  }
}

function write(key: string, value: unknown): void {
  try {
    window.sessionStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // full or blocked: the form still works, only the safety net is missing
  }
}

/** Forget the kept draft of `key` (after a successful save, or when the person discards it). */
export function clearKeptDraft(key: string): void {
  try {
    window.sessionStorage.removeItem(PREFIX + key);
  } catch {
    // nothing kept
  }
}

/**
 * Keeps what a person typed into a form through a session timeout (WP-039 session 3,
 * REQ-SEC-029 AC2; REQ-INC-019). While they type, the values are copied to this tab's session
 * storage (never to the server, never to another tab, gone when the tab closes). When the form
 * mounts again (after signing in again) they are put back, and `restored` says so, for a
 * "your unsaved input was restored" note. Call `discard()` after a successful save.
 *
 * `key` names one form and record, e.g. `incident-new` or `incident-<id>`; null keeps nothing.
 */
export function useKeptDraft<T extends FieldValues>(
  form: UseFormReturn<T>,
  key: string | null,
): { restored: boolean; discard: () => void } {
  // Known before the first render: the note shows at once, no effect sets it.
  const [restored, setRestored] = useState(() => key !== null && read(key) !== null);
  const loaded = useRef<string | null>(null);
  const { reset, watch, getValues } = form;

  useEffect(() => {
    if (key === null || loaded.current === key) return;
    loaded.current = key;
    const draft = read(key);
    if (draft !== null && typeof draft === 'object') {
      reset({ ...getValues(), ...(draft as Partial<T>) }, { keepDefaultValues: true });
    }
  }, [key, reset, getValues]);

  useEffect(() => {
    if (key === null) return;
    let timer: number | undefined;
    const subscription = watch((values) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        // An untouched form (just opened, or reset after a save) keeps nothing.
        if (JSON.stringify(values) === JSON.stringify(form.formState.defaultValues)) {
          clearKeptDraft(key);
        } else {
          write(key, values);
        }
      }, SAVE_AFTER_MS);
    });
    return () => {
      window.clearTimeout(timer);
      subscription.unsubscribe();
    };
  }, [key, watch, form.formState]);

  return {
    restored,
    discard: () => {
      if (key !== null) clearKeptDraft(key);
      setRestored(false);
    },
  };
}
