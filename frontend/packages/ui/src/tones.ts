import type { ThemeMode } from './theme';

/**
 * A coloured tag that stays readable (QA BUG-01, WP-020b). Ant Design's preset tag colours put
 * light text on a light fill (warning #faad14 on #fffbe6 is 1.82:1; success 2.2:1), below WCAG AA.
 * These pairs are at least 4.5:1 in light and dark, and 7:1 in high contrast; tones.test.tsx
 * checks every pair, so a new tone cannot drop below.
 */
export const TONES = ['default', 'info', 'success', 'warning', 'error', 'purple'] as const;
export type Tone = (typeof TONES)[number];

interface ToneColours {
  color: string;
  background: string;
  border: string;
}

export const TAG_TONES: Record<ThemeMode, Record<Tone, ToneColours>> = {
  light: {
    default: { color: '#262626', background: '#fafafa', border: '#bfbfbf' },
    info: { color: '#003eb3', background: '#e6f4ff', border: '#69b1ff' },
    success: { color: '#135200', background: '#f6ffed', border: '#95de64' },
    warning: { color: '#874d00', background: '#fffbe6', border: '#ffd666' },
    error: { color: '#a8071a', background: '#fff1f0', border: '#ff7875' },
    purple: { color: '#391085', background: '#f9f0ff', border: '#b37feb' },
  },
  dark: {
    default: { color: '#e6e6e6', background: '#1f1f1f', border: '#595959' },
    info: { color: '#91caff', background: '#111a2c', border: '#15417e' },
    success: { color: '#b7eb8f', background: '#162312', border: '#274916' },
    warning: { color: '#ffd666', background: '#2b2111', border: '#594214' },
    error: { color: '#ffa39e', background: '#2a1215', border: '#58181c' },
    purple: { color: '#d3adf7', background: '#1a1325', border: '#3e2069' },
  },
  high_contrast: {
    default: { color: '#000000', background: '#ffffff', border: '#000000' },
    info: { color: '#002c8c', background: '#ffffff', border: '#002c8c' },
    success: { color: '#092b00', background: '#ffffff', border: '#092b00' },
    warning: { color: '#613400', background: '#ffffff', border: '#613400' },
    error: { color: '#820014', background: '#ffffff', border: '#820014' },
    purple: { color: '#22075e', background: '#ffffff', border: '#22075e' },
  },
};

function luminance(hex: string): number {
  const value = hex.replace('#', '');
  const channels = [0, 2, 4].map((i) => Number.parseInt(value.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
}

/** WCAG 2.x contrast ratio of two #rrggbb colours (1 to 21). */
export function contrastRatio(foreground: string, background: string): number {
  const [light, dark] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return ((light ?? 0) + 0.05) / ((dark ?? 0) + 0.05);
}
