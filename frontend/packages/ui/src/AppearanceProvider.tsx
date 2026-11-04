import { App as AntApp, ConfigProvider } from 'antd';
import dayjs from 'dayjs';
import 'dayjs/locale/ar';
import 'dayjs/locale/ur';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { isRtlLocale, LabelsProvider, type Locale } from '@supportx/labels';

import { ANT_LOCALES } from './antdLocales';
import {
  AppearanceContext,
  type Appearance,
  type BrandingSource,
  type Direction,
} from './appearance';
import type { Density } from './density';
import { useDropdownFit } from './dropdownFit';
import { buildTheme, DEFAULT_BRANDING, type Branding, type ThemeMode } from './theme';
import { MODE_STORAGE_KEY, storedMode, systemMode } from './themeMode';

export interface AppearanceProviderProps {
  children: ReactNode;
  initialMode?: ThemeMode;
  initialLocale?: Locale;
  /** Per-tenant branding (WP-017); the Extravis default otherwise. */
  branding?: Partial<Branding>;
  /** Staff screens are compact (D-124); the portal keeps the comfortable default. */
  density?: Density;
}

/** Remembered choice, else the OS preference. */
function preferredMode(): ThemeMode {
  return storedMode() ?? systemMode();
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
  // Text for screen readers only (a name where the screen shows initials or an icon).
  '.sx-visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; ' +
  'clip: rect(0 0 0 0); white-space: nowrap; } ' +
  '.ant-table-content { overflow-x: auto; } ' +
  // Dropdown lists grow to fit their options in code (dropdownFit.ts: Ant Design's lists are
  // virtual, so CSS cannot size them by content); they never pass the screen.
  '.ant-select-dropdown { max-width: calc(100vw - 16px); } ' +
  // Option text wraps only between words ("Stacked bar", never "Sta / cked"); a single word
  // too long for the list ends in an ellipsis, its full text in the option's tooltip (title).
  '.ant-select-dropdown .ant-select-item-option .ant-select-item-option-content ' +
  '{ white-space: normal; word-break: normal; overflow-wrap: normal; overflow: hidden; ' +
  'text-overflow: ellipsis; }';

/**
 * Theme (light / dark / high contrast, brand seeds), text direction and language for everything
 * inside: Ant Design's ConfigProvider (+ its own locale), the labels provider and <html dir lang>.
 */
export function AppearanceProvider({
  children,
  initialMode,
  initialLocale = 'en',
  branding,
  density = 'comfortable',
}: AppearanceProviderProps) {
  const [mode, setModeState] = useState<ThemeMode>(() => initialMode ?? preferredMode());
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const [textScale, setTextScale] = useState(100);
  const [direction, setDirection] = useState<Direction>(isRtlLocale(initialLocale) ? 'rtl' : 'ltr');

  useEffect(() => {
    document.documentElement.dir = direction;
    document.documentElement.lang = locale;
    document.documentElement.dataset.theme = mode;
    document.documentElement.dataset.textScale = String(textScale);
  }, [direction, locale, mode, textScale]);

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
  useDropdownFit();
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
      textScale,
      setTextScale,
      setDirection,
      setBranding,
      setLocale: (next) => {
        setLocaleState(next);
        setDirection(isRtlLocale(next) ? 'rtl' : 'ltr');
      },
    }),
    [mode, direction, locale, brand, setBranding, textScale],
  );
  const themeConfig = useMemo(
    () => buildTheme(mode, brand, locale, density, textScale),
    [mode, brand, locale, density, textScale],
  );

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
