import type { LabelKey } from './en';

// Arabic is mandatory from day one (D-006). Missing keys fall back to English.
export const ar: Partial<Record<LabelKey, string>> = {
  'product.name': 'SupportX v2',
  'app.console.name': 'وحدة تحكم الفني',
  'app.portal.name': 'بوابة الخدمة الذاتية',
  'appearance.dark_mode': 'الوضع الداكن',
  'appearance.right_to_left': 'من اليمين إلى اليسار',
  'appearance.language': 'اللغة',
  'locale.en': 'English',
  'locale.ar': 'العربية',
  'locale.ur': 'اردو',
  'module.incident_management': 'إدارة الحوادث',
  'status.awaiting_customer': 'بانتظار العميل',
  'priority.p1_critical': 'P1 – حرج',
};
