import { App as AntApp, ConfigProvider } from 'antd';
import type { Locale as AntLocale } from 'antd/es/locale';
import arEG from 'antd/locale/ar_EG';
import enUS from 'antd/locale/en_US';
import urPK from 'antd/locale/ur_PK';
import dayjs from 'dayjs';
import 'dayjs/locale/ar';
import 'dayjs/locale/ur';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { isRtlLocale, LabelsProvider, type Locale } from '@supportx/labels';

import {
  AppearanceContext,
  type Appearance,
  type BrandingSource,
  type Direction,
} from './appearance';
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
 * The tab icon follows the brand (WP-017): the tenant's favicon, or back to the SupportX files the
 * page was served with. The original links are remembered once so a cleared brand restores them.
 */
function useFavicon(brand: Branding): void {
  useEffect(() => {
    const links = [
      ...document.querySelectorAll<HTMLLinkElement>(
        'link[rel="icon"], link[rel="apple-touch-icon"]',
      ),
    ];
    for (const link of links) {
      link.dataset.defaultHref ??= link.getAttribute('href') ?? '';
      const touch = link.rel === 'apple-touch-icon';
      const wanted = touch ? brand.appleTouchIcon : brand.favicon;
      const href = wanted ?? link.dataset.defaultHref;
      if (link.getAttribute('href') !== href) link.setAttribute('href', href);
      if (!touch) {
        // A type or sizes attribute from the default files would be wrong for the tenant's ICO.
        if (wanted !== undefined) link.removeAttribute('type');
      }
    }
  }, [brand.favicon, brand.appleTouchIcon]);
}

/**
 * Page-wide rules Ant Design leaves to the app. No browser margin round the page (the layout,
 * and the sidebar's border, reach every edge: QA C3), and the scrollbar's place is kept when a
 * dialog hides it, so nothing moves sideways when a dialog opens (QA C5).
 */
// A table wider than the screen scrolls inside its own box, never the page (QA BUG-03, 390 px).
const PAGE_CSS =
  'html { scrollbar-gutter: stable; } body { margin: 0; } ' +
  '.ant-table-content { overflow-x: auto; } ' +
  // Every option shows its whole label, wrapping when the list is narrow, never cut to
  // "Stacked ..." (QA WP-035 BUG-07). Lists keep the box's width, so long lists stay virtual
  // (fast, and every option keeps its accessible name).
  '.ant-select-dropdown .ant-select-item-option .ant-select-item-option-content ' +
  '{ white-space: normal; overflow: visible; text-overflow: clip; overflow-wrap: anywhere; }';

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

  const [sources, setSources] = useState<Partial<Record<BrandingSource, Partial<Branding>>>>({});
  // The tenant's brand wins over the address's, both over the prop (tests) and the default.
  const brand = useMemo<Branding>(
    () => ({ ...DEFAULT_BRANDING, ...branding, ...sources.address, ...sources.tenant }),
    [branding, sources],
  );
  const setBranding = useCallback((source: BrandingSource, next: Partial<Branding> | undefined) => {
    setSources((current) => ({ ...current, [source]: next }));
  }, []);

  useFavicon(brand);
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
      setBranding,
      setLocale: (next) => {
        setLocaleState(next);
        setDirection(isRtlLocale(next) ? 'rtl' : 'ltr');
      },
    }),
    [mode, direction, locale, brand, setBranding],
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
