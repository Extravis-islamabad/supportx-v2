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
 * REQ-ADM-058, 062): applied whenever the session changes (a save elsewhere refreshes it live).
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
    if (themeMode === null || themeMode === undefined) {
      const remembered = storedMode();
      if (remembered !== null && !copied.current) {
        copied.current = true;
        save.mutate({ field: 'theme_mode', value: remembered });
      }
      return;
    }
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
