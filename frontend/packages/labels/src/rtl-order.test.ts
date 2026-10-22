import { describe, expect, it } from 'vitest';

import { ar } from './resources/ar';
import { ur } from './resources/ur';

/*
 * Arabic and Urdu must be stored in logical (reading) order; the browser's bidi algorithm draws
 * them right-to-left. Text copied from a terminal or PDF often arrives in reversed visual order,
 * which looks plausible in some editors but renders backwards in the UI.
 *
 * Two guards: exact values for known keys (spelled out code point by code point is overkill;
 * these strings were checked letter by letter), and a structural rule that holds for any correct
 * Arabic-script word: letters that only occur at the END of a word (taa marbuta, alef maksura,
 * Urdu yeh barree) never start one. Reversed text puts them first.
 */

const WORD_FINAL_ONLY = /(^|[\s(،؛])[ةىے]/u; // ة ى ے at the start of a word
const ARABIC_SCRIPT = /[؀-ۿ]/u;

function scriptValues(resource: Partial<Record<string, string>>): [string, string][] {
  return Object.entries(resource).filter(
    (entry): entry is [string, string] =>
      typeof entry[1] === 'string' && ARABIC_SCRIPT.test(entry[1]),
  );
}

describe('RTL labels are stored in logical order', () => {
  it('known Arabic labels match their correct spelling', () => {
    expect(ar['api_status.online']).toBe('الواجهة البرمجية متصلة');
    expect(ar['api_status.offline']).toBe('الواجهة البرمجية غير متصلة');
    expect(ar['module.incident_management']).toBe('إدارة الحوادث');
    expect(ar['appearance.dark_mode']).toBe('الوضع الداكن');
    expect(ar['locale.ar']).toBe('العربية');
    expect(ar['errors.not_found']).toBe('العنصر غير موجود.');
  });

  it('known Urdu labels match their correct spelling', () => {
    expect(ur['appearance.language']).toBe('زبان');
    expect(ur['locale.ur']).toBe('اردو');
    expect(ur['api_status.online']).toBe('API آن لائن ہے');
  });

  it.each([
    ['ar', ar],
    ['ur', ur],
  ] as const)('no %s label starts a word with a word-final-only letter', (_locale, resource) => {
    const reversed = scriptValues(resource).filter(([, value]) => WORD_FINAL_ONLY.test(value));
    expect(reversed).toEqual([]);
  });

  it('the structural rule catches reversed text', () => {
    // Array.from splits by code point; Arabic letters are single code points, so this mirrors a
    // terminal's reversed visual order exactly.
    const reversedOnline = Array.from('الواجهة البرمجية متصلة').reverse().join('');
    expect(WORD_FINAL_ONLY.test(reversedOnline)).toBe(true);
    expect(WORD_FINAL_ONLY.test('الواجهة البرمجية متصلة')).toBe(false);
  });
});
