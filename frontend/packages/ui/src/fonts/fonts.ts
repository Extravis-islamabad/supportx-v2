// The fonts (D-137), bundled with the app: never loaded from the internet, so the console works
// air-gapped. All SIL OFL 1.1 (licence texts: brand/public/licenses/fonts.md, served at /licenses/fonts.md), delivered by
// the @fontsource packages (MIT packaging). woff2 only, `font-display: swap`, and subset to the
// scripts we use, so a browser downloads only the ranges a page shows:
// - Inter: Latin, Latin Extended (Turkish, Polish, ...) and Vietnamese.
// - Noto Sans Arabic: Arabic, and Urdu in Naskh (the default).
// - Noto Nastaliq Urdu: Urdu in Nastaliq, for people who choose it (My profile).
import interExt400 from '@fontsource/inter/files/inter-latin-ext-400-normal.woff2';
import interExt500 from '@fontsource/inter/files/inter-latin-ext-500-normal.woff2';
import interExt600 from '@fontsource/inter/files/inter-latin-ext-600-normal.woff2';
import interExt700 from '@fontsource/inter/files/inter-latin-ext-700-normal.woff2';
import interLatin400 from '@fontsource/inter/files/inter-latin-400-normal.woff2';
import interLatin500 from '@fontsource/inter/files/inter-latin-500-normal.woff2';
import interLatin600 from '@fontsource/inter/files/inter-latin-600-normal.woff2';
import interLatin700 from '@fontsource/inter/files/inter-latin-700-normal.woff2';
import interViet400 from '@fontsource/inter/files/inter-vietnamese-400-normal.woff2';
import nastaliq400 from '@fontsource/noto-nastaliq-urdu/files/noto-nastaliq-urdu-arabic-400-normal.woff2';
import nastaliq700 from '@fontsource/noto-nastaliq-urdu/files/noto-nastaliq-urdu-arabic-700-normal.woff2';
import naskh400 from '@fontsource/noto-sans-arabic/files/noto-sans-arabic-arabic-400-normal.woff2';
import naskh500 from '@fontsource/noto-sans-arabic/files/noto-sans-arabic-arabic-500-normal.woff2';
import naskh600 from '@fontsource/noto-sans-arabic/files/noto-sans-arabic-arabic-600-normal.woff2';
import naskh700 from '@fontsource/noto-sans-arabic/files/noto-sans-arabic-arabic-700-normal.woff2';

// The subsets' Unicode ranges, as @fontsource publishes them.
const LATIN_RANGE =
  'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD';
const LATIN_EXT_RANGE =
  'U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF';
const VIETNAMESE_RANGE =
  'U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,U+1EA0-1EF9,U+20AB';
// Arabic script: the letters Arabic and Urdu use, their digits and punctuation.
const ARABIC_RANGE =
  'U+0600-06FF,U+0750-077F,U+0870-088E,U+0890-0891,U+0897-08E1,U+08E3-08FF,U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FE74,U+FE76-FEFC';

const face = (family: string, weight: number, url: string, range: string) =>
  `@font-face{font-family:'${family}';font-style:normal;font-weight:${String(weight)};` +
  `font-display:swap;src:url(${url}) format('woff2');unicode-range:${range};}`;

/** Every @font-face rule, in one stylesheet (the appearance provider adds it once). */
export const FONT_FACES = [
  face('Inter', 400, interLatin400, LATIN_RANGE),
  face('Inter', 500, interLatin500, LATIN_RANGE),
  face('Inter', 600, interLatin600, LATIN_RANGE),
  face('Inter', 700, interLatin700, LATIN_RANGE),
  face('Inter', 400, interExt400, LATIN_EXT_RANGE),
  face('Inter', 500, interExt500, LATIN_EXT_RANGE), // every weight we use: names never faked bold
  face('Inter', 600, interExt600, LATIN_EXT_RANGE),
  face('Inter', 700, interExt700, LATIN_EXT_RANGE),
  face('Inter', 400, interViet400, VIETNAMESE_RANGE),
  face('Noto Sans Arabic', 400, naskh400, ARABIC_RANGE),
  face('Noto Sans Arabic', 500, naskh500, ARABIC_RANGE), // as Inter: every weight we use
  face('Noto Sans Arabic', 600, naskh600, ARABIC_RANGE),
  face('Noto Sans Arabic', 700, naskh700, ARABIC_RANGE),
  face('Noto Nastaliq Urdu', 400, nastaliq400, ARABIC_RANGE),
  face('Noto Nastaliq Urdu', 700, nastaliq700, ARABIC_RANGE),
].join('');

/** How Urdu is set (D-137): Naskh by default, Nastaliq for those who choose it. */
export type UrduScript = 'naskh' | 'nastaliq';

// The system stack after the bundled faces: only for characters none of them covers.
const SYSTEM = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial";

/**
 * THE font tokens: the family (and line height) per UI language and Urdu style. Nastaliq is
 * much taller than Naskh, so it gets taller lines (nothing clips in tags, rows, inputs, menus).
 */
export function fontFor(
  locale: 'en' | 'ar' | 'ur',
  urduScript: UrduScript,
): { fontFamily: string; lineHeight?: number } {
  if (locale === 'ur' && urduScript === 'nastaliq') {
    return { fontFamily: `Inter, 'Noto Nastaliq Urdu', ${SYSTEM}, sans-serif`, lineHeight: 1.9 };
  }
  if (locale === 'en') return { fontFamily: `Inter, 'Noto Sans Arabic', ${SYSTEM}, sans-serif` };
  return { fontFamily: `Inter, 'Noto Sans Arabic', ${SYSTEM}, sans-serif`, lineHeight: 1.7 };
}
