import { createContext, useContext } from 'react';

import { useLabels, type LabelInput, type LabelParams, type Locale } from '@supportx/labels';

import type { Branding, ThemeMode } from './theme';

export type Direction = 'ltr' | 'rtl';

export interface Appearance {
  mode: ThemeMode;
  direction: Direction;
  locale: Locale;
  branding: Branding;
  setMode: (mode: ThemeMode) => void;
  setDirection: (direction: Direction) => void;
  setLocale: (locale: Locale) => void;
  /**
   * Replace the brand from one source (WP-017): `address` (before sign-in, from the host) or
   * `tenant` (the signed-in tenant's, which wins). `undefined` clears that source.
   */
  setBranding: (source: BrandingSource, branding: Partial<Branding> | undefined) => void;
}

export type BrandingSource = 'address' | 'tenant';

export const AppearanceContext = createContext<Appearance | null>(null);

export function useAppearance(): Appearance {
  const appearance = useContext(AppearanceContext);
  if (appearance === null) {
    throw new Error('useAppearance must be used inside <AppearanceProvider>');
  }
  return appearance;
}

/** `t(key, params)` in the current locale (react-i18next underneath, D-013). */
export function useLabel(): (key: LabelInput, params?: LabelParams) => string {
  return useLabels();
}
