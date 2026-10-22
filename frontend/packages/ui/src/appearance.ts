import { createContext, useContext } from 'react';

import { label, type LabelKey, type Locale } from '@supportx/labels';

export type ThemeMode = 'light' | 'dark';
export type Direction = 'ltr' | 'rtl';

export interface Appearance {
  mode: ThemeMode;
  direction: Direction;
  locale: Locale;
  setMode: (mode: ThemeMode) => void;
  setDirection: (direction: Direction) => void;
  setLocale: (locale: Locale) => void;
}

export const AppearanceContext = createContext<Appearance | null>(null);

export function useAppearance(): Appearance {
  const appearance = useContext(AppearanceContext);
  if (appearance === null) {
    throw new Error('useAppearance must be used inside <AppearanceProvider>');
  }
  return appearance;
}

/** Label lookup bound to the current locale. */
export function useLabel(): (key: LabelKey) => string {
  const { locale } = useAppearance();
  return (key) => label(key, locale);
}
