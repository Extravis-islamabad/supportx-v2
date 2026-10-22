// English is the reference dictionary: every key must exist here (CI-enforced later, §9.5).
export const en = {
  'product.name': 'SupportX v2',
  'app.console.name': 'Technician Console',
  'app.portal.name': 'Self-Service Portal',
  'appearance.dark_mode': 'Dark mode',
  'appearance.right_to_left': 'Right-to-left',
  'appearance.language': 'Language',
  'locale.en': 'English',
  'locale.ar': 'العربية',
  'locale.ur': 'اردو',
  'module.incident_management': 'Incident Management',
  'status.awaiting_customer': 'Awaiting Customer',
  'priority.p1_critical': 'P1 – Critical',
} as const;

export type LabelKey = keyof typeof en;
