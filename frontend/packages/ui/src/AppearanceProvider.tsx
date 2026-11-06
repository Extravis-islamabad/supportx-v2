import { App as AntApp, ConfigProvider } from 'antd';
import dayjs from 'dayjs';
import 'dayjs/locale/ar';
import 'dayjs/locale/ur';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { isRtlLocale, LabelsProvider, type Locale } from '@supportx/labels';

import { ANT_LOCALES } from './antdLocales';
import { fontFaces, type UrduScript } from './fonts/fonts';
import {
  AppearanceContext,
  intlLocaleFor,
  type Appearance,
  type Digits,
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
  // A table wider than its box shows that it scrolls: a real scrollbar, never an overlay one
  // that appears only while scrolling (QA 2026-11-05 V1: columns cut off with no cue).
  '.ant-table-content { scrollbar-width: thin; scrollbar-color: rgba(127, 127, 127, 0.55) transparent; } ' +
  '.ant-table-content::-webkit-scrollbar { height: 10px; } ' +
  '.ant-table-content::-webkit-scrollbar-thumb { background: rgba(127, 127, 127, 0.55); border-radius: 5px; } ' +
  // Tabs that do not fit scroll sideways instead of moving into a "more" menu: Ant Design puts
  // that menu's button inside the tab list, which may hold only tabs (axe aria-required-children,
  // the record at 390 px; UI pass 2).
  '.ant-tabs-nav-operations { display: none !important; } ' +
  '.ant-tabs > .ant-tabs-nav .ant-tabs-nav-wrap { overflow-x: auto; scrollbar-width: thin; } ' +
  '.ant-tabs > .ant-tabs-nav .ant-tabs-nav-list { transform: none !important; } ' +
  // Dropdown lists grow to fit their options in code (dropdownFit.ts: Ant Design's lists are
  // virtual, so CSS cannot size them by content); they never pass the screen.
  '.ant-select-dropdown { max-width: calc(100vw - 16px); } ' +
  // Multi-select tags show their whole text: no clipped descenders, readable Arabic and Urdu
  // (QA6S-SHELL-08: the single-line padding rule below no longer reaches them).
  '.ant-select-multiple .ant-select-selection-item { height: auto; min-height: 24px; ' +
  'line-height: 1.6; padding-block: 1px; } ' +
  '.ant-select-multiple .ant-select-selection-item-content { line-height: 1.6; } ' +
  // Option text wraps only between words ("Stacked bar", never "Sta / cked"); a single word
  // too long for the list ends in an ellipsis, its full text in the option's tooltip (title).
  // Room for the dots below Arabic-script letters wherever one line of user text is cut off
  // (QA 2026-11-04: "في" read as "فى"), whatever the UI language: the clip box (the padding
  // box) grows, and the equal negative margin keeps the layout exactly as it was. Two-line
  // clamps take the script's line height instead (clampLineHeight).
  '.ant-typography-ellipsis-single-line, .ant-card-head-title, .ant-select-single .ant-select-selection-item, ' +
  '.ant-select-item-option-content, .ant-menu-title-content ' +
  '{ padding-block: 0.25em; margin-block: -0.25em; } ' +
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
  const [urduScript, setUrduScript] = useState<UrduScript>('naskh');
  const [textScale, setTextScale] = useState(100);
  const [digits, setDigits] = useState<Digits>('western');
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
      digits,
      setDigits,
      intlLocale: intlLocaleFor(locale, digits),
      setDirection,
      setBranding,
      urduScript,
      setUrduScript,
      setLocale: (next) => {
        setLocaleState(next);
        setDirection(isRtlLocale(next) ? 'rtl' : 'ltr');
      },
    }),
    [mode, direction, locale, brand, setBranding, urduScript, textScale, digits],
  );
  const themeConfig = useMemo(
    () => buildTheme(mode, brand, locale, density, textScale, urduScript),
    [mode, brand, locale, density, textScale, urduScript],
  );

  return (
    <AppearanceContext.Provider value={appearance}>
      <style>{fontFaces(urduScript) + PAGE_CSS}</style>
      <LabelsProvider locale={locale}>
        <ConfigProvider direction={direction} locale={ANT_LOCALES[locale]} theme={themeConfig}>
          {/* Messages start below the header, never over its search field (UI pass 2, agreed
              with lane B); the header grows with the text size. Notifications stay top-right. */}
          <AntApp message={{ top: Math.round((56 * textScale) / 100) + 8 }}>{children}</AntApp>
        </ConfigProvider>
      </LabelsProvider>
    </AppearanceContext.Provider>
  );
}
