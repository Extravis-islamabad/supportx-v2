import i18next, { type i18n as I18n } from 'i18next';

import { humanize } from './humanize';
import { ar } from './resources/ar';
import { en, type LabelKey } from './resources/en';
import { ur } from './resources/ur';

export const LOCALES = ['en', 'ar', 'ur'] as const;
export type Locale = (typeof LOCALES)[number];

/** Values interpolated into a label, e.g. `{{days}}` (i18next syntax; `count` picks plurals). */
export type LabelParams = Record<string, string | number | boolean | null | undefined>;

/** A label key, or any system code that should have one (falls back to humanize()). */
export type LabelInput = LabelKey | (string & {});

const RTL_LOCALES: ReadonlySet<Locale> = new Set(['ar', 'ur']);
const reportedMissing = new Set<string>();

export function isRtlLocale(locale: Locale): boolean {
  return RTL_LOCALES.has(locale);
}

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

/** Last resort for a key no locale has: readable text plus a one-time warning (§9.5). */
function missing(key: string): string {
  if (!reportedMissing.has(key)) {
    reportedMissing.add(key);
    console.warn(`[labels] missing label for "${key}"`);
  }
  return humanize(key);
}

/**
 * A fresh i18next instance with every locale loaded (resources are bundled, so it initialises
 * synchronously). Keys are flat ('errors.not_found'): dots are part of the key, not a path.
 * Lookup order: requested locale, English, then humanize() with a missing-label warning.
 * Plurals follow CLDR rules per locale (Arabic has six forms: `_zero`, `_one`, `_two`, `_few`,
 * `_many`, `_other`).
 */
export function createI18n(locale: Locale = 'en'): I18n {
  const instance = i18next.createInstance();
  void instance.init({
    resources: {
      en: { translation: en },
      ar: { translation: ar },
      ur: { translation: ur },
    },
    lng: locale,
    fallbackLng: 'en',
    supportedLngs: [...LOCALES],
    keySeparator: false,
    nsSeparator: false,
    // React escapes output itself; double escaping would show "&amp;" to users.
    interpolation: { escapeValue: false },
    initAsync: false,
    returnNull: false,
    parseMissingKeyHandler: missing,
  });
  return instance;
}

/** Shared instance for code outside React (and the default for the React provider). */
export const i18n = createI18n();

/**
 * Display text for a label key or system code in `locale`, with optional interpolation params.
 * React components use `useLabel()` from @supportx/ui instead, which follows the user's locale.
 */
export function label(key: LabelInput, locale: Locale = 'en', params?: LabelParams): string {
  return i18n.getFixedT(locale)(key, params);
}
