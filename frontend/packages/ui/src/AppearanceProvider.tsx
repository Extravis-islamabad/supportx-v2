import { App as AntApp, ConfigProvider } from 'antd';
import type { Locale as AntLocale } from 'antd/es/locale';
import arEG from 'antd/locale/ar_EG';
import enUS from 'antd/locale/en_US';
import urPK from 'antd/locale/ur_PK';
import dayjs from 'dayjs';
import 'dayjs/locale/ar';
import 'dayjs/locale/ur';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

import { isRtlLocale, LabelsProvider, type Locale } from '@supportx/labels';

import { AppearanceContext, type Appearance, type Direction } from './appearance';
import { buildTheme, DEFAULT_BRANDING, THEME_MODES, type Branding, type ThemeMode } from './theme';

const ANT_LOCALES: Record<Locale, AntLocale> = { en: enUS, ar: arEG, ur: urPK };
const MODE_STORAGE_KEY = 'supportx.theme_mode';

export interface AppearanceProviderProps {
  children: ReactNode;
  initialMode?: ThemeMode;
  initialLocale?: Locale;
  /** Per-tenant branding (WP-017); the Extravis default otherwise. */
  branding?: Partial<Branding>;
}

/** Remembered choice, else the OS preference. Storage may be unavailable (private mode). */
function preferredMode(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(MODE_STORAGE_KEY);
    if (stored !== null && (THEME_MODES as readonly string[]).includes(stored)) {
      return stored as ThemeMode;
    }
  } catch {
    // ignore: the OS preference is a fine default
  }
  if (window.matchMedia('(prefers-contrast: more)').matches) return 'high_contrast';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/**
 * Page-wide rules Ant Design leaves to the app. No browser margin round the page (the layout,
 * and the sidebar's border, reach every edge: QA C3), and the scrollbar's place is kept when a
 * dialog hides it, so nothing moves sideways when a dialog opens (QA C5).
 */
// A table wider than the screen scrolls inside its own box, never the page (QA BUG-03, 390 px).
const PAGE_CSS =
  'html { scrollbar-gutter: stable; } body { margin: 0; } ' +
  '.ant-table-content { overflow-x: auto; }';

/**
 * Theme (light / dark / high contrast, brand seeds), text direction and language for everything
 * inside: Ant Design's ConfigProvider (+ its own locale), the labels provider and <html dir lang>.
 */
export function AppearanceProvider({
  children,
  initialMode,
  initialLocale = 'en',
  branding,
}: AppearanceProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(() => initialMode ?? preferredMode());
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const [direction, setDirection] = useState<Direction>(isRtlLocale(initialLocale) ? 'rtl' : 'ltr');

  useEffect(() => {
    document.documentElement.dir = direction;
    document.documentElement.lang = locale;
    document.documentElement.dataset.theme = mode;
  }, [direction, locale, mode]);

  // Ant Design's pickers take month and weekday names from dayjs's global locale.
  useEffect(() => {
    dayjs.locale(locale);
  }, [locale]);

  const brand = useMemo(() => ({ ...DEFAULT_BRANDING, ...branding }), [branding]);
  const appearance = useMemo<Appearance>(
    () => ({
      mode,
      direction,
      locale,
      branding: brand,
      setMode: (next) => {
        setModeState(next);
        try {
          window.localStorage.setItem(MODE_STORAGE_KEY, next);
        } catch {
          // not persisted: still applied for this visit
        }
      },
      setDirection,
      setLocale: (next) => {
        setLocaleState(next);
        setDirection(isRtlLocale(next) ? 'rtl' : 'ltr');
      },
    }),
    [mode, direction, locale, brand],
  );
  const themeConfig = useMemo(() => buildTheme(mode, brand, locale), [mode, brand, locale]);

  return (
    <AppearanceContext.Provider value={appearance}>
      <style>{PAGE_CSS}</style>
      <LabelsProvider locale={locale}>
        <ConfigProvider direction={direction} locale={ANT_LOCALES[locale]} theme={themeConfig}>
          <AntApp>{children}</AntApp>
        </ConfigProvider>
      </LabelsProvider>
    </AppearanceContext.Provider>
  );
}
