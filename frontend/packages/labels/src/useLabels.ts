import { useTranslation } from 'react-i18next';

import { FSI, isRtlLocale, PDI, type LabelInput, type LabelParams, type Locale } from './label';

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

export type ListKind = 'conjunction' | 'disjunction' | 'unit';

/**
 * Joins items the way the UI language does: "A, B, and C" / "A أو B" / "A، B" (QA WP-035
 * BUG-05). `disjunction` for "any of these" (a filter's "is one of"), `conjunction` for "all of
 * these", `unit` for a plain list. Items are isolated (FSI/PDI) in right-to-left languages, so a
 * Latin name inside Arabic keeps its order. Never join visible lists with ", " by hand.
 */
export function useListFormat(): (items: readonly string[], kind?: ListKind) => string {
  const { i18n } = useTranslation();
  return (items, kind = 'unit') => formatList(i18n.language, items, kind);
}

/** `useListFormat` outside React (a given language). */
export function formatList(
  locale: string,
  items: readonly string[],
  kind: ListKind = 'unit',
): string {
  const rtl = isRtlLocale(locale as Locale);
  const shown = rtl ? items.map((item) => `${FSI}${item}${PDI}`) : items;
  return new Intl.ListFormat(locale, { type: kind }).format(shown);
}
