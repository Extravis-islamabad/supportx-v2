import type { LabelKey } from './en';

// Urdu skeleton: mandatory from Stage 2 (D-006). Missing keys fall back to English.
export const ur: Partial<Record<LabelKey, string>> = {
  'product.name': 'SupportX v2',
  'appearance.language': 'زبان',
  'locale.en': 'English',
  'locale.ar': 'العربية',
  'locale.ur': 'اردو',
};
