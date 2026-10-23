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
        lineWidth: 2,
        controlOutlineWidth: 3,
      },
      components: {
        Layout: { siderBg: '#ffffff', headerBg: '#ffffff' },
        Menu: { itemSelectedBg: '#000000', itemSelectedColor: '#ffffff' },
      },
    };
  }
  return {
    algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: { ...SHARED, colorPrimary: brand.colorPrimary },
  };
}

/** Darken a #rrggbb colour by `amount` (0..1) toward black. */
export function darken(hex: string, amount: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (match?.[1] === undefined) return hex;
  const value = Number.parseInt(match[1], 16);
  const channels = [value >> 16, (value >> 8) & 0xff, value & 0xff].map((channel) =>
    Math.round(channel * (1 - amount)),
  );
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`;
}
