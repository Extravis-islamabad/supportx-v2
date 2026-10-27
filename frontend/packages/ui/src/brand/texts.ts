import type { Locale } from '@supportx/labels';

import type { Branding, BrandTextKey } from '../theme';

/** A tenant text in `locale`, else in English, else undefined (the caller shows its label). */
export function brandText(
  branding: Branding,
  key: BrandTextKey,
  locale: Locale,
): string | undefined {
  const texts = branding.texts?.[key];
  const found = texts?.[locale] ?? texts?.en;
  return found === undefined || found === '' ? undefined : found;
}
