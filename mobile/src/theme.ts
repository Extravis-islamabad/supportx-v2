import { useColorScheme } from 'react-native';

import { BRAND, darken, PRIMARY_HOVER_DARKEN, RADIUS, SURFACE_COLOURS } from '@supportx/ui/tokens';

/**
 * The mobile look (D-155: the prototype's soft lilac page, white cards, purple primary), on the
 * shared tokens. Every text colour reaches 4.5:1 on its background in both modes.
 */
const MOBILE = {
  light: {
    layout: '#F6F4FB',
    border: '#E7E3F1',
    strongBorder: '#D0C8E4',
    text: '#1B1530',
    textSecondary: '#57516B',
    link: '#6B33B8',
    muted: '#F1EEF8',
  },
  dark: {
    layout: SURFACE_COLOURS.dark.layout,
    border: SURFACE_COLOURS.dark.border,
    strongBorder: '#5B5470',
    text: SURFACE_COLOURS.dark.text,
    textSecondary: SURFACE_COLOURS.dark.textSecondary,
    link: '#C4A6F0',
    muted: '#221C33',
  },
} as const;

/** Colours for the phone's light or dark mode, from the same tokens as the web theme. */
export function usePalette() {
  const mode = useColorScheme() === 'dark' ? 'dark' : 'light';
  return {
    ...SURFACE_COLOURS[mode],
    ...MOBILE[mode],
    mode,
    primary: BRAND.primary,
    primaryPressed: darken(BRAND.primary, PRIMARY_HOVER_DARKEN),
    // White on the brand primary: 5.93:1, on its pressed shade 7.16:1 (theme.ts).
    onPrimary: '#ffffff',
    radius: RADIUS,
  };
}

export type Palette = ReturnType<typeof usePalette>;

export const SPACE = { xs: 4, sm: 8, md: 16, lg: 24 } as const;
