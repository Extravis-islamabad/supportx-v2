import { useEffect, useRef, useState } from 'react';
import type { FieldValues, UseFormReturn } from 'react-hook-form';

import { useSession } from '@supportx/api-client';

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

function remove(key: string): void {
  try {
    window.sessionStorage.removeItem(PREFIX + key);
  } catch {
    // nothing kept
  }
}

/**
 * Forget every kept draft of this tab. Called on an explicit sign-out (never on a timeout), so
 * the next person at a shared computer starts clean.
 */
export function clearAllKeptDrafts(): void {
  try {
    for (const name of Object.keys(window.sessionStorage)) {
      if (name.startsWith(PREFIX)) window.sessionStorage.removeItem(name);
    }
  } catch {
    // nothing kept
  }
}

/**
 * Keeps what a person typed into a form through a session timeout (WP-039 session 3,
 * REQ-SEC-029 AC2; REQ-INC-019). While they type, the values are copied to this tab's session
 * storage (never to the server, never to another tab, gone when the tab closes), under the
 * signed-in tenant and person: someone else signing in on the same tab, or the same person in
 * another organisation, never gets them. When the form mounts again (after signing in again)
 * they are put back and `restored` says so. `discard()` forgets them (after a successful save);
 * `startEmpty(values)` forgets them and resets the form to `values`.
 *
 * `key` names one form and record, e.g. `incident-new` or `incident-<id>`; null keeps nothing.
 */
export function useKeptDraft<T extends FieldValues>(
  form: UseFormReturn<T>,
  key: string | null,
): { restored: boolean; discard: () => void; startEmpty: (values: T) => void } {
  const session = useSession().data;
  const scoped =
    key === null || session === undefined || session === null
      ? null
      : `${session.tenant.id}.${session.user.id}.${key}`;
  // Known before the first render: the note shows at once, no effect sets it.
  const [restored, setRestored] = useState(() => scoped !== null && read(scoped) !== null);
  const loaded = useRef<string | null>(null);
  const formRef = useRef(form);
  const { reset, watch, getValues } = form;

  useEffect(() => {
    formRef.current = form;
  });

  useEffect(() => {
    if (scoped === null || loaded.current === scoped) return;
    loaded.current = scoped;
    const draft = read(scoped);
    if (draft !== null && typeof draft === 'object') {
      reset({ ...getValues(), ...(draft as Partial<T>) }, { keepDefaultValues: true });
    }
  }, [scoped, reset, getValues]);

  useEffect(() => {
    if (scoped === null) return;
    let timer: number | undefined;
    const subscription = watch((values) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        // An untouched form (just opened, or reset after a save) keeps nothing.
        const defaults = formRef.current.formState.defaultValues;
        if (JSON.stringify(values) === JSON.stringify(defaults)) remove(scoped);
        else write(scoped, values);
      }, SAVE_AFTER_MS);
    });
    return () => {
      window.clearTimeout(timer);
      subscription.unsubscribe();
    };
  }, [scoped, watch]);

  const discard = () => {
    if (scoped !== null) remove(scoped);
    setRestored(false);
  };
  return {
    restored,
    discard,
    startEmpty: (values: T) => {
      discard();
      reset(values);
    },
  };
}
