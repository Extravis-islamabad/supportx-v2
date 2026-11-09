import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export interface SettingsDraft<T extends Record<string, unknown>> {
  /** What the form shows: the saved values with this person's edits on top. */
  draft: T;
  /** Change some fields. */
  set: (patch: Partial<T>) => void;
  /** How many fields differ from what is saved (the save bar's count). */
  changes: number;
  /** Only the changed fields, for the PATCH body. */
  changed: Partial<T>;
  /** Back to what is saved. */
  discard: () => void;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * A settings page's edits, for its one save bar (D-147 template E, #258): every card edits the
 * same draft, the bar counts the changed fields, Discard returns to what is saved, and a save
 * sends only what changed. When the saved values change underneath (a live update, or this
 * person's own save) and nothing is being edited, the draft follows them.
 */
export function useSettingsDraft<T extends Record<string, unknown>>(saved: T): SettingsDraft<T> {
  const [edits, setEdits] = useState<Partial<T>>({});
  const savedRef = useRef(saved);
  useEffect(() => {
    // Edits that now match what is saved are no longer edits (a save just landed them).
    if (savedRef.current !== saved) {
      savedRef.current = saved;
      setEdits((current) => {
        const kept = Object.entries(current).filter(([key, value]) => !same(value, saved[key]));
        return Object.fromEntries(kept) as Partial<T>;
      });
    }
  }, [saved]);
  const set = useCallback((patch: Partial<T>) => {
    setEdits((current) => ({ ...current, ...patch }));
  }, []);
  const discard = useCallback(() => {
    setEdits({});
  }, []);
  return useMemo(() => {
    const changed = Object.fromEntries(
      Object.entries(edits).filter(([key, value]) => !same(value, saved[key])),
    ) as Partial<T>;
    return {
      draft: { ...saved, ...edits },
      set,
      changes: Object.keys(changed).length,
      changed,
      discard,
    };
  }, [edits, saved, set, discard]);
}
