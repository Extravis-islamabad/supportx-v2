import { theme as antdTheme, type ThemeConfig } from 'antd';

export const THEME_MODES = ['light', 'dark', 'high_contrast'] as const;
export type ThemeMode = (typeof THEME_MODES)[number];

/**
 * What a tenant may brand (WP-017 will load it per tenant; until then the Extravis default).
 * Everything else in the theme derives from these seeds, so a tenant colour changes buttons,
 * links, focus rings and selected menu items consistently in every mode.
 */
export interface Branding {
  /** Seed for every primary shade, e.g. '#9619B5'. */
  colorPrimary: string;
  /** Logo URL (S3 asset in WP-017); the product name is shown when absent. */
  logoUrl?: string;
}

/** Extravis brand purple. White text on it has a 6.8:1 contrast ratio (WCAG AA). */
export const DEFAULT_BRANDING: Branding = { colorPrimary: '#9619B5' };

const SHARED: ThemeConfig['token'] = {
  borderRadius: 6,
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans Arabic', 'Noto Nastaliq Urdu', 'Helvetica Neue', Arial, sans-serif",
};

/**
 * Ant Design theme for a mode and a branding. Light and dark use Ant Design's algorithms on the
 * brand seed. High contrast is a light theme with pure black text and borders, thicker lines
 * and a darker primary so every text/background pair exceeds WCAG AAA (7:1) where possible.
 */
export function buildTheme(mode: ThemeMode, branding: Partial<Branding> = {}): ThemeConfig {
  const brand = { ...DEFAULT_BRANDING, ...branding };
  if (mode === 'high_contrast') {
    return {
      algorithm: antdTheme.defaultAlgorithm,
      token: {
        ...SHARED,
        colorPrimary: darken(brand.colorPrimary, 0.35),
        colorText: '#000000',
        colorTextSecondary: '#1f1f1f',
        colorTextTertiary: '#262626',
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
          colorTextSecondary: 'rgba(0, 0, 0, 0.68)',
          colorTextTertiary: 'rgba(0, 0, 0, 0.62)',
          colorTextDescription: 'rgba(0, 0, 0, 0.62)',
          colorTextPlaceholder: 'rgba(0, 0, 0, 0.58)',
          // Ant Design's #ff4d4f is about 3.3:1 on white as button text; this red is about 5:1.
          colorError: '#cf1322',
        };
  if (mode !== 'dark') {
    return {
      algorithm: antdTheme.defaultAlgorithm,
      token: { ...SHARED, ...readable, colorPrimary: brand.colorPrimary },
    };
  }
  // The dark algorithm keeps a deep brand colour as the primary, which Menu, Tabs and links use
  // for *text*: a purple like #9619B5 then reads at about 1.6:1 on the dark selected background
  // (axe, WP-016). Selected and active text uses a light tint of the brand instead.
  const primaryText = lighten(brand.colorPrimary, 0.5);
  return {
    algorithm: antdTheme.darkAlgorithm,
    token: {
      ...SHARED,
      ...readable,
      colorPrimary: brand.colorPrimary,
      colorLink: primaryText,
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

/** Darken a #rrggbb colour by `amount` (0..1) toward black. */
export function darken(hex: string, amount: number): string {
  return mix(hex, amount, 0);
}

/** Lighten a #rrggbb colour by `amount` (0..1) toward white. */
export function lighten(hex: string, amount: number): string {
  return mix(hex, amount, 255);
}

function mix(hex: string, amount: number, target: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (match?.[1] === undefined) return hex;
  const value = Number.parseInt(match[1], 16);
  const channels = [value >> 16, (value >> 8) & 0xff, value & 0xff].map((channel) =>
    Math.round(channel + (target - channel) * amount),
  );
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}
