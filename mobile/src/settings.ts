import { getLocales } from 'expo-localization';
import * as SecureStore from 'expo-secure-store';
import { create } from 'zustand';

import { onSessionId, setApiOrigin, setCsrfToken, setSessionId } from '@supportx/api-client';
import { isLocale, type Locale } from '@supportx/labels';

// Device-local settings (docs/architecture/mobile.md: Zustand holds the server URL, tenant and
// UI preferences), kept in SecureStore (Keychain / Keystore). The session ID is the one secret:
// it lives here and in the API client's memory only, never in logs or other storage (ADR-044).
const SERVER_KEY = 'supportx.server';
const LOCALE_KEY = 'supportx.locale';
const SESSION_KEY = 'supportx.session';

export interface SettingsState {
  /** The SupportX server's origin, e.g. https://support.example.com; null until chosen. */
  server: string | null;
  /** The signed-in session's ID (sent as `X-SupportX-Session`); null when signed out. */
  session: string | null;
  /**
   * The server ended the session (it timed out, or was ended from another device or by an admin):
   * the sign-in screen says so. Phones keep the web's session limits (ADR-044, D-154).
   */
  sessionEnded: boolean;
  locale: Locale;
  loaded: boolean;
  load: () => Promise<void>;
  setServer: (origin: string) => Promise<void>;
  setSession: (id: string | null) => Promise<void>;
  /** A 401: forget the session and tell the person why they are signing in again. */
  endSession: () => Promise<void>;
  setLocale: (locale: Locale) => Promise<void>;
}

/** The phone's first preferred language we have labels for, else English. */
export function deviceLocale(): Locale {
  for (const { languageCode } of getLocales()) {
    if (languageCode !== null && isLocale(languageCode)) return languageCode;
  }
  return 'en';
}

async function keep(key: string, value: string | null): Promise<void> {
  if (value === null) await SecureStore.deleteItemAsync(key);
  else await SecureStore.setItemAsync(key, value);
}

export const useSettings = create<SettingsState>()((set, get) => ({
  server: null,
  session: null,
  sessionEnded: false,
  locale: 'en',
  loaded: false,
  load: async () => {
    const [server, session, locale] = await Promise.all([
      SecureStore.getItemAsync(SERVER_KEY),
      SecureStore.getItemAsync(SESSION_KEY),
      SecureStore.getItemAsync(LOCALE_KEY),
    ]);
    setApiOrigin(server);
    setSessionId(server === null ? null : session);
    set({
      server,
      session: server === null ? null : session,
      locale: locale !== null && isLocale(locale) ? locale : deviceLocale(),
      loaded: true,
    });
  },
  setServer: async (origin) => {
    // Another server: the old session means nothing there.
    if (get().server !== origin) await get().setSession(null);
    await SecureStore.setItemAsync(SERVER_KEY, origin);
    setApiOrigin(origin);
    set({ server: origin });
  },
  setSession: async (id) => {
    setSessionId(id);
    if (id === null) setCsrfToken(null);
    set(id === null ? { session: null } : { session: id, sessionEnded: false });
    await keep(SESSION_KEY, id);
  },
  endSession: async () => {
    await get().setSession(null);
    set({ sessionEnded: true });
  },
  setLocale: async (locale) => {
    set({ locale });
    await SecureStore.setItemAsync(LOCALE_KEY, locale);
  },
}));

// A tenant switch hands out a new session ID: keep it, or the next start would sign in again.
onSessionId((id) => {
  void useSettings.getState().setSession(id);
});
