import i18next, { type i18n as I18n } from 'i18next';

import { humanize } from './humanize';
import rtlRanges from './rtl-ranges.json';
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
/** Unicode first-strong isolate and pop directional isolate. */
export const FSI = '\u2068';
export const PDI = '\u2069';

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
  const t = i18n.getFixedT(locale);
  return t(key, isolatedFor(t(key), params, locale));
}

const WHOLE_PLACEHOLDER = /^\s*\{\{\s*\w+\s*\}\}\s*$/;

/**
 * `params` isolated for the label whose unfilled text is `template`: a label that is only one
 * placeholder ("{{message}}") is the value itself, with nothing around it to keep apart from.
 */
export function isolatedFor(
  template: string,
  params: LabelParams | undefined,
  locale: Locale,
): LabelParams | undefined {
  return WHOLE_PLACEHOLDER.test(template) ? params : isolateParams(params, locale);
}

// Directional isolates U+2066..U+2069; a value starting with one is already isolated.
const ISOLATES = /[\u2066-\u2069]/g;
const OPENERS = /^[\u2066\u2067\u2068]/;
// Display IDs and thread tokens ("INC-12", "[INC-12]") stay as typed: they are matched and pasted.
const TOKEN = /^\[?[A-Z]{2,10}-\d{1,12}\]?$/;
// i18next's own options are not values to show.
const OPTIONS = new Set([
  'count',
  'context',
  'defaultValue',
  'ordinal',
  'ns',
  'lng',
  'returnObjects',
]);

/** Text without directional isolates: a pasted "INC-12" or name with marks still matches. */
export function stripIsolates(text: string): string {
  return text.replace(ISOLATES, '');
}

// Right-to-left letters: code points with bidi class R or AL (generated from Python's Unicode data
// by `make labels-json`; the server tests the same class directly).
const RTL_LETTERS = new RegExp(
  `[${(rtlRanges.ranges as [number, number][])
    .map(([first, last]) => `\\u{${first.toString(16)}}-\\u{${last.toString(16)}}`)
    .join('')}]`,
  'u',
);

/**
 * A filled value as shown: isolated (FSI…PDI) when its direction can differ from the sentence's,
 * i.e. the sentence is right-to-left (ar, ur) or the value has right-to-left letters. Numbers,
 * display IDs and values already isolated are left as they are. The server's rule
 * (app/shared/labels `isolate`); isolation-cases.json holds both to the same results.
 */
export function isolateValue<T>(value: T, locale: Locale): T | string {
  if (typeof value !== 'string' || value === '' || OPENERS.test(value) || TOKEN.test(value)) {
    return value;
  }
  return isRtlLocale(locale) || RTL_LETTERS.test(value) ? `${FSI}${value}${PDI}` : value;
}

/** The values of `params` isolated by the rule above (i18next's options left alone). */
export function isolateParams(
  params: LabelParams | undefined,
  locale: Locale,
): LabelParams | undefined {
  if (params === undefined) return params;
  const out: LabelParams = {};
  for (const [name, value] of Object.entries(params)) {
    out[name] = OPTIONS.has(name) ? value : isolateValue(value, locale);
  }
  return out;
}
