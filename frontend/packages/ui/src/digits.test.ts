import { describe, expect, it } from 'vitest';

import { intlLocaleFor } from './appearance';

// D-135: Western digits by default in every language; Arabic-Indic only when chosen.
describe('intlLocaleFor', () => {
  const number = (locale: string) => new Intl.NumberFormat(locale).format(1234);

  it('pins Western digits by default, Arabic and Urdu included', () => {
    for (const language of ['en', 'ar', 'ur']) {
      expect(number(intlLocaleFor(language, 'western'))).toMatch(/^1\D?234$/);
    }
  });

  it('writes Arabic-Indic digits when chosen (Urdu uses the extended forms)', () => {
    expect(number(intlLocaleFor('ar', 'arabic_indic'))).toMatch(/١.?٢٣٤/);
    expect(number(intlLocaleFor('ur', 'arabic_indic'))).toMatch(/۱.?۲۳۴/);
  });
});
