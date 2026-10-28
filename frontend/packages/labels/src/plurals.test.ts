import { describe, expect, it } from 'vitest';

import { ar } from './resources/ar';
import { en } from './resources/en';
import { ur } from './resources/ur';

// QA WP-029 BUG-04: a counted label in Arabic needs all six CLDR plural forms, or i18next falls
// back to English for the forms it lacks ("Automation stopped 4 loops…" on an Arabic screen).
// Urdu has two (one, other). A label counts when it has plural forms in English, or when its
// text puts {{count}} into a sentence; a number shown as a value ("People: {{count}}",
// "History ({{count}})") reads the same for every number and needs no forms.

const SUFFIXES = ['zero', 'one', 'two', 'few', 'many', 'other'] as const;
const AR_FORMS = SUFFIXES;
const UR_FORMS = ['one', 'other'] as const;
const VALUE_ONLY = /^[^{}]*(?::\s*\{\{count\}\}|\(\{\{count\}\}\))[^{}]*$/;

type Resource = Partial<Record<string, string>>;

/** Base keys of counted labels: plural families in English, plus counts used in sentences. */
export function countedLabels(english: Resource): string[] {
  const keys = new Set(Object.keys(english));
  const bases = new Set<string>();
  for (const key of keys) {
    const base = key.replace(/_(one|other)$/, '');
    if (base !== key && keys.has(`${base}_one`) && keys.has(`${base}_other`)) bases.add(base);
  }
  for (const [key, text] of Object.entries(english)) {
    const base = key.replace(/_(zero|one|two|few|many|other)$/, '');
    if (bases.has(base)) continue;
    if (text?.includes('{{count}}') === true && !VALUE_ONLY.test(text)) bases.add(key);
  }
  return [...bases].sort();
}

function missingForms(resource: Resource, bases: string[], forms: readonly string[]): string[] {
  return bases.flatMap((base) =>
    forms.map((form) => `${base}_${form}`).filter((key) => !(key in resource)),
  );
}

describe('BUG-04: counted labels have every plural form', () => {
  const bases = countedLabels(en);

  it('BUG-04: finds counted labels, including counts inside sentences', () => {
    expect(bases).toContain('automation.loop.banner');
    expect(VALUE_ONLY.test('People: {{count}}')).toBe(true);
    expect(VALUE_ONLY.test('History ({{count}})')).toBe(true);
    expect(VALUE_ONLY.test('{{count}} files')).toBe(false);
  });

  it('BUG-04: English has one and other for every counted label', () => {
    expect(missingForms(en, bases, ['one', 'other'])).toEqual([]);
  });

  it('BUG-04: Arabic has zero, one, two, few, many and other for every counted label', () => {
    expect(missingForms(ar, bases, AR_FORMS)).toEqual([]);
  });

  it('BUG-04: Urdu has one and other for every counted label', () => {
    expect(missingForms(ur, bases, UR_FORMS)).toEqual([]);
  });

  it('BUG-04: no counted label keeps a bare key next to its forms', () => {
    const bare = bases.filter((base) => base in en || base in ar || base in ur);
    expect(bare).toEqual([]);
  });
});
