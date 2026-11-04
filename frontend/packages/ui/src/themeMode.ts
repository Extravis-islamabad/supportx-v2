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
