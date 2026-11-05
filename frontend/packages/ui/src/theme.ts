import { theme as antdTheme, type ThemeConfig } from 'antd';

import type { Locale } from '@supportx/labels';

import { SUPPORTX_COLOURS, SUPPORTX_LOGOS, type BrandLogos } from './brand';
import { densityTheme, type Density } from './density';
import { fontFor, type UrduScript } from './fonts/fonts';
import {
  darken,
  LIGHT_SURFACE,
  lighten,
  PRIMARY_ACTIVE_DARKEN,
  PRIMARY_HOVER_DARKEN,
  RADIUS,
} from './tokens';

export { darken, lighten } from './tokens';

export const THEME_MODES = ['light', 'dark', 'high_contrast'] as const;
export type ThemeMode = (typeof THEME_MODES)[number];

/**
 * What a tenant may brand (WP-017 will load it per tenant; until then the SupportX defaults from
 * ./brand, docs/architecture/branding.md). Everything else in the theme derives from these seeds,
 * so a tenant colour changes buttons, links, focus rings and selected menu items consistently in
 * every mode.
 */
export interface Branding {
  /** Seed for every primary shade, e.g. '#7e40d1'. White text on it must reach 4.5:1. */
  colorPrimary: string;
  /** Decorative gradient (start, end): header accent, portal welcome band. */
  gradient: readonly [string, string];
  /** Logo files; the product name is shown when a variant is missing. */
  logos: BrandLogos;
  /** Tab icon and home-screen icon URLs (WP-017); the SupportX files when absent. */
  favicon?: string;
  appleTouchIcon?: string;
  /** Tenant texts per language (English is the fallback); the labels' defaults when absent. */
  texts?: BrandTexts;
}

export type BrandTextKey = 'productName' | 'portalName' | 'welcomeText';
export type BrandTexts = Partial<Record<BrandTextKey, Partial<Record<Locale, string>>>>;

/**
 * The SupportX brand: primary #7e40d1 (the logo gradient's midpoint; white text 5.93:1), gradient
 * #6060de to #951ab6 (the logo's ends, the start darkened 6% so white text reaches 4.97:1).
 */
export const DEFAULT_BRANDING: Branding = {
  colorPrimary: SUPPORTX_COLOURS.primary,
  gradient: SUPPORTX_COLOURS.gradient,
  logos: SUPPORTX_LOGOS,
};

/**
 * The console's frame (UI pass 2, docs/design/target): a dark indigo navigation in every theme
 * mode, beside or above a white top bar. Measured: menu text #C9C4DB on #16122B 10.7:1, white on
 * the selected #2C2552 14.1:1, white on the count badge #3A3168 11.5:1.
 */
export const SHELL = {
  navBg: '#16122B',
  navSelectedBg: '#2C2552',
  navHoverBg: '#221C40',
  navText: '#C9C4DB',
  navBadgeBg: '#3A3168',
} as const;

/** The target's light surfaces: a cool grey page, white cards with 1px borders. */
const LIGHT_SURFACES = {
  colorText: LIGHT_SURFACE.text,
  colorBgLayout: LIGHT_SURFACE.layout,
  colorBorder: LIGHT_SURFACE.border,
  colorBorderSecondary: LIGHT_SURFACE.borderSecondary,
  colorFillAlter: LIGHT_SURFACE.fillAlter,
  colorSplit: LIGHT_SURFACE.split,
} as const;

// The font tokens live in ./fonts (D-137): bundled faces, switched by language and Urdu style.
function shared(locale: Locale, urduScript: UrduScript): ThemeConfig['token'] {
  return { borderRadius: RADIUS, ...fontFor(locale, urduScript) };
}

/**
 * Ant Design theme for a mode and a branding. Light and dark use Ant Design's algorithms on the
 * brand seed. High contrast is a light theme with pure black text and borders, thicker lines
 * and a darker primary so every text/background pair exceeds WCAG AAA (7:1) where possible.
 */
export function buildTheme(
  mode: ThemeMode,
  branding: Partial<Branding> = {},
  locale: Locale = 'en',
  density: Density = 'comfortable',
  textScale = 100,
  urduScript: UrduScript = 'naskh',
): ThemeConfig {
  return scaleText(themeFor(mode, branding, locale, density, urduScript), textScale);
}

/** Text sizes a person may choose, in percent (WP-042, REQ-ADM-062). */
export const TEXT_SCALES = [90, 100, 110, 120, 130, 140, 150] as const;

// Ant Design's own seeds where a theme leaves them out (Ant Design 5 defaults).
const SEED = { fontSize: 14, controlHeight: 32 } as const;

/**
 * Text, and the controls and rows around it, grown or shrunk by `percent` (REQ-ADM-062): every
 * font size the theme sets, plus the heights a larger line needs so nothing is cut off.
 */
function scaleText(config: ThemeConfig, percent: number): ThemeConfig {
  if (percent === 100) return config;
  const by = (value: number) => Math.round((value * percent) / 100);
  const token: Record<string, unknown> = { ...config.token };
  for (const key of ['fontSize', 'controlHeight'] as const) {
    token[key] = by(config.token?.[key] ?? SEED[key]);
  }
  for (const [key, value] of Object.entries(token)) {
    if (key.startsWith('fontSizeHeading') && typeof value === 'number') token[key] = by(value);
  }
  const components: Record<string, Record<string, unknown>> = {};
  for (const [name, tokens] of Object.entries(config.components ?? {})) {
    const scaled: Record<string, unknown> = { ...(tokens as Record<string, unknown>) };
    for (const [key, value] of Object.entries(scaled)) {
      if (typeof value === 'number' && /FontSize$|^itemHeight$|^headerHeight/.test(key)) {
        scaled[key] = by(value);
      }
    }
    components[name] = scaled;
  }
  return {
    ...config,
    token: token,
    components: components,
  };
}

function themeFor(
  mode: ThemeMode,
  branding: Partial<Branding>,
  locale: Locale,
  density: Density,
  urduScript: UrduScript,
): ThemeConfig {
  const base = modeTheme(mode, branding, locale, urduScript);
  const dense = densityTheme(density, base.algorithm ?? antdTheme.defaultAlgorithm);
  const components = { ...base.components };
  for (const [name, tokens] of Object.entries(dense.components ?? {})) {
    const key = name as keyof NonNullable<ThemeConfig['components']>;
    components[key] = { ...(components[key] as object), ...tokens } as never;
  }
  return withShell({
    ...base,
    algorithm: dense.algorithm,
    // The mode's own tokens win (high contrast line widths, readable colours); Urdu keeps its
    // taller line height, so rows grow rather than clip.
    token: { ...dense.token, ...base.token },
    components,
  });
}

/** The dark navigation's tokens, in every mode (Ant Design's `dark` Sider and Menu). */
function withShell(config: ThemeConfig): ThemeConfig {
  const components = { ...config.components };
  components.Layout = {
    ...components.Layout,
    siderBg: SHELL.navBg,
    triggerBg: SHELL.navSelectedBg,
    triggerColor: '#FFFFFF',
  };
  components.Menu = {
    ...components.Menu,
    darkItemBg: SHELL.navBg,
    darkSubMenuItemBg: SHELL.navBg,
    darkPopupBg: SHELL.navBg,
    darkItemColor: SHELL.navText,
    darkItemHoverBg: SHELL.navHoverBg,
    darkItemHoverColor: '#FFFFFF',
    darkItemSelectedBg: SHELL.navSelectedBg,
    darkItemSelectedColor: '#FFFFFF',
  };
  return { ...config, components };
}

function modeTheme(
  mode: ThemeMode,
  branding: Partial<Branding>,
  locale: Locale,
  urduScript: UrduScript,
): ThemeConfig {
  const brand = { ...DEFAULT_BRANDING, ...branding };
  const base = shared(locale, urduScript);
  if (mode === 'high_contrast') {
    return {
      algorithm: antdTheme.defaultAlgorithm,
      token: {
        ...base,
        colorPrimary: darken(brand.colorPrimary, 0.35),
        colorLink: darken(brand.colorPrimary, 0.35),
        colorText: '#000000',
        colorTextSecondary: '#1f1f1f',
        colorTextTertiary: '#262626',
        // Ant Design's default placeholder is 1.84:1 on white; this one is 7:1 (theme-contrast.test).
        colorTextPlaceholder: '#595959',
        colorBorder: '#000000',
        colorBorderSecondary: '#000000',
        colorBgLayout: '#ffffff',
        // Danger buttons show their text in colorError; Ant Design's default red is about 3.3:1
        // on white, this one about 7.6:1 (axe on the incident page, WP-020).
        colorError: '#a8071a',
        lineWidth: 2,
        controlOutlineWidth: 3,
      },
      components: {
        Layout: { lightSiderBg: '#ffffff', headerBg: '#ffffff' },
        Menu: { itemSelectedBg: '#000000', itemSelectedColor: '#ffffff' },
        Segmented: { itemSelectedBg: '#000000', itemSelectedColor: '#ffffff' },
      },
    };
  }
  // Ant Design's default secondary/description text (45% opacity) is about 4:1 on its
  // background: below WCAG AA for normal text (4.5:1). Raised here (axe, WP-010).
  const readable =
    mode === 'dark'
      ? {
          colorTextSecondary: 'rgba(255, 255, 255, 0.75)',
          colorTextTertiary: 'rgba(255, 255, 255, 0.68)',
          colorTextDescription: 'rgba(255, 255, 255, 0.68)',
          colorTextPlaceholder: 'rgba(255, 255, 255, 0.6)',
          // Danger buttons and links show their text in colorError (WP-012, axe).
          colorError: '#ff7875',
        }
      : {
          // #5A6070: 6.28:1 on white, 5.76:1 on the #F4F5F7 page (UI pass 2).
          colorTextSecondary: '#5A6070',
          colorTextTertiary: '#5A6070',
          colorTextDescription: '#5A6070',
          colorTextPlaceholder: 'rgba(0, 0, 0, 0.58)',
          // Ant Design's #ff4d4f is about 3.3:1 on white as button text; this red is about 5:1.
          colorError: '#cf1322',
        };
  // Ant Design lightens a primary button on hover; white text on the lighter shade can drop below
  // 4.5:1. Hover and press darken instead (white on the SupportX hover shade: 7.16:1).
  const pressed = {
    colorPrimaryHover: darken(brand.colorPrimary, PRIMARY_HOVER_DARKEN),
    colorPrimaryActive: darken(brand.colorPrimary, PRIMARY_ACTIVE_DARKEN),
  };
  if (mode !== 'dark') {
    return {
      algorithm: antdTheme.defaultAlgorithm,
      token: {
        ...base,
        ...readable,
        ...pressed,
        ...LIGHT_SURFACES,
        colorPrimary: brand.colorPrimary,
        // Links a shade deeper than the brand (the target's #6B33B8: 7.5:1 on white); Ant
        // Design's default link blue is about 4.1:1.
        colorLink: darken(brand.colorPrimary, 0.15),
        colorLinkHover: pressed.colorPrimaryActive,
        colorLinkActive: pressed.colorPrimaryActive,
      },
    };
  }
  // The dark algorithm keeps a deep brand colour as the primary, which Menu, Tabs and links use
  // for *text*: a deep purple (#9619B5) read at about 1.6:1 on the dark selected background
  // (axe, WP-016). Selected and active text uses a light tint of the brand instead.
  const primaryText = lighten(brand.colorPrimary, 0.5);
  return {
    algorithm: antdTheme.darkAlgorithm,
    token: {
      ...base,
      ...readable,
      ...pressed,
      colorPrimary: brand.colorPrimary,
      colorLink: primaryText,
      colorLinkHover: primaryText,
      colorLinkActive: primaryText,
      colorPrimaryText: primaryText,
    },
    components: {
      // The sidebar uses Ant Design's "light" sider, whose colours are fixed (white): give it
      // the container colours of the dark mode instead, so dark mode has a dark sidebar.
      Layout: {
        lightSiderBg: '#141414',
        lightTriggerBg: '#1f1f1f',
        lightTriggerColor: 'rgba(255, 255, 255, 0.85)',
      },
      Menu: {
        itemSelectedColor: primaryText,
        // The top-bar layout (WP-011) uses the horizontal menu, with its own tokens.
        horizontalItemSelectedColor: primaryText,
        horizontalItemHoverColor: primaryText,
        subMenuItemSelectedColor: primaryText, // "More" when the current section is inside it
      },
      Tabs: { itemSelectedColor: primaryText, itemActiveColor: primaryText },
    },
  };
}
