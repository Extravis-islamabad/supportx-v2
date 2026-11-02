import { describe, expect, it } from 'vitest';

import cases from './isolation-cases.json';
import {
  FSI,
  isolateValue,
  label,
  PDI,
  stripIsolates,
  type LabelParams,
  type Locale,
} from './label';

// The console and the server fill labels the same way: the shared cases file is the contract.
describe('isolation rule: the console matches the server (isolation-cases.json)', () => {
  it.each(cases.cases)('$key in $locale', ({ key, locale, params, text }) => {
    expect(label(key, locale as Locale, params as LabelParams)).toBe(text);
  });

  it('never wraps a value twice, a number, or a display ID', () => {
    expect(isolateValue(`${FSI}x${PDI}`, 'ar')).toBe(`${FSI}x${PDI}`);
    expect(isolateValue(5, 'ar')).toBe(5);
    expect(isolateValue('[INC-12]', 'ar')).toBe('[INC-12]');
  });

  it('strips marks from pasted text', () => {
    expect(stripIsolates(`${FSI}INC-12${PDI}`)).toBe('INC-12');
  });
});
