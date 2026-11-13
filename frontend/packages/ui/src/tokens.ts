import palette from './brand/palette.json';

/**
 * Design tokens with no UI-library import, so a non-web app (the React Native mobile app,
 * docs/architecture/mobile.md) styles itself from the same values as the Ant Design theme.
 * theme.ts builds the web theme from these; `@supportx/ui/tokens` is the only entry the mobile
 * app may import from this package (everything else needs antd or the DOM).
 */
export const BRAND = {
  /** Primary seed (gradient midpoint): white text on it reaches 5.93:1. */
  primary: palette.primary,
  gradient: [palette.gradient.start, palette.gradient.end] as const,
} as const;

/** Same amounts as tooling/brand_assets.py (the Keycloak login page uses its hover shade too). */
export const PRIMARY_HOVER_DARKEN = 0.12;
export const PRIMARY_ACTIVE_DARKEN = 0.2;

export const RADIUS = 8;

/** The light surfaces of UI pass 2 (docs/design/target): a cool grey page, white cards, 1px borders. */
export const LIGHT_SURFACE = {
  text: '#14161B',
  layout: '#F4F5F7',
  border: '#D5D8DF',
  borderSecondary: '#E3E5EA',
  fillAlter: '#F8F9FB',
  split: '#EEF0F3',
} as const;

/**
 * Text and status colours that pass WCAG AA on the mode's background (axe, WP-010 and WP-012):
 * the defaults of Ant Design's algorithms are raised where they fall short.
 */
export const SURFACE_COLOURS = {
  light: {
    background: '#ffffff',
    layout: LIGHT_SURFACE.layout,
    border: LIGHT_SURFACE.border,
    text: LIGHT_SURFACE.text,
    // #5A6070: 6.28:1 on white, 5.76:1 on the #F4F5F7 page (UI pass 2).
    textSecondary: '#5A6070',
    textTertiary: '#5A6070',
    placeholder: 'rgba(0, 0, 0, 0.58)',
    error: '#cf1322',
    success: '#237804',
  },
  dark: {
    background: '#141414',
    layout: '#000000',
    border: '#424242',
    text: 'rgba(255, 255, 255, 0.85)',
    textSecondary: 'rgba(255, 255, 255, 0.75)',
    textTertiary: 'rgba(255, 255, 255, 0.68)',
    placeholder: 'rgba(255, 255, 255, 0.6)',
    error: '#ff7875',
    success: '#95de64',
  },
} as const;

export type SurfaceMode = keyof typeof SURFACE_COLOURS;

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
