import { LOCALES, type Locale } from '@supportx/labels';

import { THEME_MODES, type ThemeMode } from './theme';

export const MODE_STORAGE_KEY = 'supportx.theme_mode';

/**
 * The theme this browser remembers (before the person's own is read from the server, and the
 * one copied to the server once when they never chose: WP-042). Null when none or unreadable.
 */
export function storedMode(): ThemeMode | null {
  try {
    const stored = window.localStorage.getItem(MODE_STORAGE_KEY);
    if (stored !== null && (THEME_MODES as readonly string[]).includes(stored)) {
      return stored as ThemeMode;
    }
  } catch {
    // storage unavailable (private mode)
  }
  return null;
}

/** What the operating system asks for: high contrast, dark or light. */
export function systemMode(): ThemeMode {
  if (window.matchMedia('(prefers-contrast: more)').matches) return 'high_contrast';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export const LOCALE_STORAGE_KEY = 'supportx.locale';

/**
 * The UI language this browser last showed, so the screen before the session is read (the
 * loading splash) is already in it (QA 2026-11-12 V-01). Null when none or unreadable.
 */
export function storedLocale(): Locale | null {
  try {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (stored !== null && (LOCALES as readonly string[]).includes(stored)) return stored as Locale;
  } catch {
    // storage unavailable (private mode)
  }
  return null;
}

/** Remember the person's UI language for the next visit's first screen. */
export function rememberLocale(locale: Locale): void {
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    // not persisted: the next visit starts in English until the session is read
  }
}
