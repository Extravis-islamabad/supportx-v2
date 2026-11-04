import { useEffect, useRef } from 'react';

import {
  readPending,
  useSetPreference,
  type MeResponse,
  type PersonalPreferenceChange,
} from '@supportx/api-client';
import { reportError, storedMode, systemMode, useAppearance, type ThemeMode } from '@supportx/ui';

const PERSONAL = ['theme_mode', 'text_scale', 'week_start', 'date_format', 'time_format'] as const;

/**
 * The person's theme and text size, from the server, on every tab and device (WP-042;
 * REQ-ADM-058, 062). A browser with no theme of its own takes the person's at once (a new
 * device); a browser that remembers one keeps it as it opens (it mirrors the last one applied
 * there), and a change made anywhere while it is open applies here too (the session refreshes
 * live).
 * Someone who never chose gets the theme this browser remembers copied to the server once; with
 * nothing remembered, the system's applies and nothing is stored. Returns the save for a theme
 * picked in the header.
 */
export function usePersonalAppearance(
  user: MeResponse['user'] | undefined,
): (mode: ThemeMode) => void {
  const { setMode, setTextScale } = useAppearance();
  const save = useSetPreference(user?.id ?? '');
  const copied = useRef(false);
  // The first theme read from the server since this tab opened. A value, not a "done" flag:
  // React's StrictMode runs effects twice in development, and a flag would let the second run
  // apply the server's theme over this browser's own.
  const firstSeen = useRef<{ value: string | null } | 'changed' | null>(null);
  const userId = user?.id;
  const themeMode = user?.theme_mode;
  const textScale = user?.text_scale;

  // Choices made just before a reload whose save had not finished: sent again (as the layout).
  useEffect(() => {
    if (userId === undefined) return;
    const pending = readPending(userId);
    for (const field of PERSONAL) {
      const value = pending[field];
      if (value !== undefined) save.mutate({ field, value } as PersonalPreferenceChange);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per signed-in user
  }, [userId]);

  useEffect(() => {
    if (userId === undefined) return;
    const remembered = storedMode();
    const value = themeMode ?? null;
    if (firstSeen.current === null) firstSeen.current = { value };
    else if (firstSeen.current !== 'changed' && firstSeen.current.value !== value) {
      firstSeen.current = 'changed';
    }
    const opening = firstSeen.current !== 'changed';
    if (themeMode === null || themeMode === undefined) {
      if (remembered !== null && !copied.current) {
        copied.current = true;
        save.mutate({ field: 'theme_mode', value: remembered });
      }
      return;
    }
    if (opening && remembered !== null) return; // this browser's own, as it opens
    setMode(themeMode === 'system' ? systemMode() : themeMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- applies the server's value only
  }, [userId, themeMode]);

  useEffect(() => {
    if (textScale !== undefined) setTextScale(textScale);
  }, [textScale, setTextScale]);

  return (mode) => {
    save.mutate({ field: 'theme_mode', value: mode }, { onError: reportError });
  };
}
