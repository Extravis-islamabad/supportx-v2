import { useTranslation } from 'react-i18next';

import type { LabelInput, LabelParams } from './label';

/** `t(key, params)` bound to the current locale; re-renders when the language changes. */
export function useLabels(): (key: LabelInput, params?: LabelParams) => string {
  const { t } = useTranslation();
  return (key, params) => t(key, params);
}

/**
 * `t(locale, key, params)`: a label in a given language, whatever the UI's (WP-020c-FIX:
 * suggesting names in every language). Missing keys fall back as usual (Urdu → English).
 */
export function useLabelsIn(): (locale: string, key: LabelInput, params?: LabelParams) => string {
  const { i18n } = useTranslation();
  return (locale, key, params) => i18n.getFixedT(locale)(key, params);
}
