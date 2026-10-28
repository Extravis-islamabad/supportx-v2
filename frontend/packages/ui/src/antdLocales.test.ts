import enUS from 'antd/locale/en_US';
import { describe, expect, it } from 'vitest';

import { ANT_LOCALES, antLocaleOf } from './antdLocales';

function englishLeft(english: unknown, other: unknown, path = ''): string[] {
  if (typeof english === 'string') {
    // Formats (dates, times) are the same characters in every language; the rest is words.
    if (path.endsWith('Format')) return [];
    if (typeof other !== 'string') return [`${path}: missing`];
    return /[A-Za-z]{2}/.test(english) && other === english ? [`${path}: "${other}"`] : [];
  }
  if (english === null || typeof english !== 'object' || Array.isArray(english)) return [];
  return Object.entries(english).flatMap(([key, value]) =>
    englishLeft(
      value,
      (other as Record<string, unknown> | undefined)?.[key],
      path ? `${path}.${key}` : key,
    ),
  );
}

describe('Ant Design texts in right-to-left languages (QA WP-023)', () => {
  it.each(['ar', 'ur'] as const)('%s has no Ant Design text left in English', (locale) => {
    expect(englishLeft(enUS, ANT_LOCALES[locale])).toEqual([]);
  });

  it('Urdu tables say "no data" in Urdu', () => {
    expect(ANT_LOCALES.ur.Table?.emptyText).toBe('کوئی ڈیٹا نہیں');
    expect(ANT_LOCALES.ur.Empty?.description).not.toBe('No data');
  });
});

describe('the locale object Ant Design gets (QA WP-023, the browser\'s English "No data")', () => {
  it('unwraps a CommonJS module wrapper, as Vite pre-bundling hands it over', () => {
    const wrapped = { __esModule: true, default: enUS };
    expect(antLocaleOf(wrapped)).toBe(enUS);
  });

  it.each(['en', 'ar', 'ur'] as const)('%s is a real locale, never a wrapper', (locale) => {
    expect(ANT_LOCALES[locale].locale).toBe(locale);
    expect(ANT_LOCALES[locale].Empty?.description).toBeTruthy();
  });
});
