import { createContext, useContext } from 'react';

import { useLabels, type LabelInput, type LabelParams, type Locale } from '@supportx/labels';

import type { UrduScript } from './fonts/fonts';
import type { Branding, ThemeMode } from './theme';

export type Direction = 'ltr' | 'rtl';
/** Digits on screen (D-135). */
export type Digits = 'western' | 'arabic_indic';

/** `locale` with its numbering system: Western (`latn`) unless Arabic-Indic was chosen. */
export function intlLocaleFor(locale: string, digits: Digits): string {
  // Urdu writes the extended Arabic-Indic digits (۰-۹), Arabic and others ٠-٩.
  const system = digits === 'arabic_indic' ? (locale === 'ur' ? 'arabext' : 'arab') : 'latn';
  return `${locale}-u-nu-${system}`;
}

export interface Appearance {
  mode: ThemeMode;
  direction: Direction;
  locale: Locale;
  branding: Branding;
  setMode: (mode: ThemeMode) => void;
  /**
   * The locale for numbers and dates (`Intl`): the language with its digits pinned (D-135).
   * Western digits by default in every language; Arabic-Indic when the person chose them.
   * Labels keep `locale`.
   */
  intlLocale: string;
  digits: Digits;
  setDigits: (digits: Digits) => void;
  /** Text size in percent, 90 to 150 (WP-042, REQ-ADM-062); 100 unless the person chose. */
  textScale: number;
  setTextScale: (percent: number) => void;
  setDirection: (direction: Direction) => void;
  setLocale: (locale: Locale) => void;
  /**
   * Replace the brand from one source (WP-017): `address` (before sign-in, from the host) or
   * `tenant` (the signed-in tenant's, which wins). `undefined` clears that source.
   */
  setBranding: (source: BrandingSource, branding: Partial<Branding> | undefined) => void;
  /** How Urdu is set (D-137): Naskh by default, Nastaliq when the person chose it. */
  urduScript: UrduScript;
  setUrduScript: (script: UrduScript) => void;
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
