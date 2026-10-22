import type { LabelKey } from './en';

// Urdu skeleton: mandatory from Stage 2 (D-006). Missing keys fall back to English.
export const ur: Partial<Record<LabelKey, string>> = {
  'product.name': 'SupportX v2',
  'appearance.language': 'زبان',
  'locale.en': 'English',
  'locale.ar': 'العربية',
  'locale.ur': 'اردو',
  'api_status.checking': 'API کی جانچ ہو رہی ہے…',
  'api_status.online': 'API آن لائن ہے',
  'api_status.offline': 'API آف لائن ہے',
  'auth.sign_out': 'سائن آؤٹ',
  'auth.checking_session': 'آپ کا سیشن چیک کیا جا رہا ہے…',
  'auth.redirecting_to_login': 'سائن اِن کی طرف بھیجا جا رہا ہے…',
};
