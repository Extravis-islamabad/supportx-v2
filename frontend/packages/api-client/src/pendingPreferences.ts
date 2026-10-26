// Preferences chosen but not yet confirmed by the server (QA flaky BUG-04 test, WP-020c-FIX).
// The screen changes at once (optimistic); the save takes two requests. Without this, a reload
// during that window silently lost the choice. Kept per user in this browser until the save
// succeeds or is refused; the console re-sends what is still pending when it starts.

export interface PendingPreferences {
  ui_locale?: 'en' | 'ar' | 'ur' | null;
  nav_layout?: string;
  form_density?: string;
}

const key = (userId: string) => `supportx.pending_preferences.${userId}`;

export function readPending(userId: string): PendingPreferences {
  try {
    const raw = window.localStorage.getItem(key(userId));
    return raw === null ? {} : (JSON.parse(raw) as PendingPreferences);
  } catch {
    return {}; // storage blocked (private mode): nothing pending, nothing lost but this
  }
}

function write(userId: string, value: PendingPreferences): void {
  try {
    if (Object.keys(value).length === 0) window.localStorage.removeItem(key(userId));
    else window.localStorage.setItem(key(userId), JSON.stringify(value));
  } catch {
    // Storage unavailable: the save itself still happens.
  }
}

export function setPending<K extends keyof PendingPreferences>(
  userId: string,
  field: K,
  value: PendingPreferences[K],
): void {
  write(userId, { ...readPending(userId), [field]: value });
}

/**
 * After a failed save: forget the choice only when the server refused it. A save cut off by a
 * reload or a dropped connection stays pending (the page aborts its requests while it unloads,
 * and that error arrives before the page is gone): the next start sends it again.
 */
export function settlePendingAfterError<K extends keyof PendingPreferences>(
  userId: string,
  field: K,
  value: PendingPreferences[K],
  error: unknown,
): void {
  const status = (error as { status?: unknown } | null)?.status;
  if (typeof status === 'number' && status >= 400 && status < 500) {
    clearPending(userId, field, value);
  }
}

/** Done with `field` (saved or refused), unless a newer choice is waiting. */
export function clearPending<K extends keyof PendingPreferences>(
  userId: string,
  field: K,
  value: PendingPreferences[K],
): void {
  const current = readPending(userId);
  if (!(field in current) || current[field] !== value) return;
  write(userId, Object.fromEntries(Object.entries(current).filter(([name]) => name !== field)));
}
