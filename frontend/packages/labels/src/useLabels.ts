import { useCallback } from 'react';
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
  const language = i18n.language;
  // Stable per language, so callers may use it inside useMemo.
  return useCallback(
    (items: readonly string[], kind: ListKind = 'unit') => formatList(language, items, kind),
    [language],
  );
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

/**
 * Parts shown side by side ("P1 · Open"): each isolated in right-to-left languages, so a Latin
 * part never swaps places with its neighbours (QA WP-035 BUG-04).
 */
export function useJoinParts(): (parts: readonly string[], separator?: string) => string {
  const { i18n } = useTranslation();
  const rtl = isRtlLocale(i18n.language as Locale);
  // Stable per direction, so callers may use it inside useMemo.
  return useCallback(
    (parts: readonly string[], separator = ' · ') =>
      (rtl ? parts.map((p) => `${FSI}${p}${PDI}`) : parts).join(separator),
    [rtl],
  );
}

/**
 * `isolate(value)`: a value placed inside right-to-left text (a number, date or Latin name in an
 * Arabic sentence), wrapped in Unicode isolates so it keeps its own order (QA WP-035 BUG-04).
 * Unchanged in left-to-right languages. The server's `label()` isolates every value it fills.
 */
export function useIsolate(): (value: string | number) => string {
  const { i18n } = useTranslation();
  const rtl = isRtlLocale(i18n.language as Locale);
  // Stable per direction, so callers may use it inside useMemo.
  return useCallback(
    (value: string | number) => (rtl ? `${FSI}${String(value)}${PDI}` : String(value)),
    [rtl],
  );
}
