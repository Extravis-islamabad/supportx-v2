import { humanize } from './humanize';
import { ar } from './resources/ar';
import { en, type LabelKey } from './resources/en';
import { ur } from './resources/ur';

export const LOCALES = ['en', 'ar', 'ur'] as const;
export type Locale = (typeof LOCALES)[number];

const resources: Record<Locale, Partial<Record<string, string>>> = { en, ar, ur };
const RTL_LOCALES: ReadonlySet<Locale> = new Set(['ar', 'ur']);
const reportedMissing = new Set<string>();

export function isRtlLocale(locale: Locale): boolean {
  return RTL_LOCALES.has(locale);
}

/**
 * Display text for a label key or system code. Lookup order: requested locale, English, then
 * humanize() with a one-time missing-label warning (architecture.md §9.5).
 */
export function label(key: LabelKey | (string & {}), locale: Locale = 'en'): string {
  const text = resources[locale][key] ?? resources.en[key];
  if (text !== undefined) {
    return text;
  }
  if (!reportedMissing.has(key)) {
    reportedMissing.add(key);
    console.warn(`[labels] missing label for "${key}"`);
  }
  return humanize(key);
}
