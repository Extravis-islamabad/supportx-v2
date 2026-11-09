// WP-042 (REQ-ADM-106, 107, 108): every setup page, once. The setup home, the setup menu, setup
// search and the command palette all read this map; a test checks that every admin route is in
// it. Labels: `setup.group.<group>`, `nav.admin_<key>` (the page name),
// `setup.page.<key>.description` and `setup.page.<key>.keywords` (comma-separated words and
// synonyms, in each language).

import type { LabelKey } from '@supportx/labels';

export const SETUP_GROUPS = [
  'people_access',
  'service_desk',
  'automation_sla',
  'channels',
  'organisation',
  'licence',
  'audit',
] as const;
export type SetupGroup = (typeof SETUP_GROUPS)[number];

export interface SetupPage {
  /** The route under /admin, also the test id suffix (`admin-sections-<key>`). */
  key: string;
  group: SetupGroup;
  /** `nav.admin_<labelKey>`: the page name. */
  labelKey: LabelKey;
  permission: string;
  /** A second permission that also opens the page. */
  also?: string;
}

export const SETUP_PAGES: readonly SetupPage[] = [
  { key: 'users', group: 'people_access', labelKey: 'nav.admin_users', permission: 'users.view' },
  {
    key: 'organization',
    group: 'people_access',
    labelKey: 'nav.admin_organization',
    permission: 'sites.view',
  },
  { key: 'roles', group: 'people_access', labelKey: 'nav.admin_roles', permission: 'roles.view' },
  {
    key: 'security',
    group: 'people_access',
    labelKey: 'nav.admin_security',
    permission: 'identity.manage',
  },
  {
    key: 'api-keys',
    group: 'people_access',
    labelKey: 'nav.admin_api_keys',
    permission: 'api_keys.manage',
  },
  {
    key: 'incidents',
    group: 'service_desk',
    labelKey: 'nav.admin_incidents',
    // The service desk's configure right (WP-042), or settings.manage for every area.
    permission: 'config.service_desk',
    also: 'settings.manage',
  },
  {
    key: 'requests',
    group: 'service_desk',
    labelKey: 'nav.admin_requests',
    permission: 'config.service_desk',
    also: 'settings.manage',
  },
  // WP-032 D8 (REQ-PRT-031): every portal setting on one page.
  {
    key: 'portal',
    group: 'service_desk',
    labelKey: 'nav.admin_portal',
    permission: 'config.service_desk',
    also: 'settings.manage',
  },
  // WP-031: what people can request (catalog_items.manage; admins hold every permission).
  {
    key: 'catalog',
    group: 'service_desk',
    labelKey: 'nav.admin_catalog',
    permission: 'catalog_items.manage',
  },
  // Knowledge settings or its article types (D-120): either permission opens the page.
  {
    key: 'knowledge',
    group: 'service_desk',
    labelKey: 'nav.admin_knowledge',
    permission: 'knowledge.manage_settings',
    also: 'knowledge.manage_types',
  },
  {
    key: 'automation',
    group: 'automation_sla',
    labelKey: 'nav.admin_automation',
    permission: 'automation.view',
  },
  { key: 'ai', group: 'automation_sla', labelKey: 'nav.admin_ai', permission: 'ai.manage' },
  { key: 'sla', group: 'automation_sla', labelKey: 'nav.admin_sla', permission: 'sla.view' },
  {
    key: 'mail',
    group: 'channels',
    labelKey: 'nav.admin_mail',
    permission: 'integrations.manage_email',
  },
  {
    key: 'notifications',
    group: 'channels',
    labelKey: 'nav.admin_notifications',
    permission: 'notifications.manage',
  },
  {
    key: 'integrations',
    group: 'channels',
    labelKey: 'nav.admin_integrations',
    permission: 'integrations.view',
  },
  {
    key: 'branding',
    group: 'organisation',
    labelKey: 'nav.admin_branding',
    permission: 'branding.manage',
  },
  {
    key: 'instance',
    group: 'organisation',
    labelKey: 'nav.admin_instance',
    permission: 'config.organisation',
    also: 'settings.manage',
  },
  { key: 'files', group: 'organisation', labelKey: 'nav.admin_files', permission: 'files.manage' },
  { key: 'licence', group: 'licence', labelKey: 'nav.admin_licence', permission: 'licence.manage' },
  { key: 'audit', group: 'audit', labelKey: 'nav.audit', permission: 'audit.view' },
];

/**
 * Every permission that opens a setup page: the sidebar shows Admin to anyone holding one of
 * them, so the Admin link and the setup menu always agree (coverage 2026-11-09 §17 item 1).
 */
export const SETUP_PERMISSIONS: readonly string[] = [
  ...new Set(SETUP_PAGES.flatMap((page) => [page.permission, ...(page.also ? [page.also] : [])])),
];

/** Pages this person may open, in map order. */
export function pagesFor(can: (permission: string) => boolean): SetupPage[] {
  return SETUP_PAGES.filter(
    (page) => can(page.permission) || (page.also !== undefined && can(page.also)),
  );
}

/** Letters only, case and Arabic marks folded, so "Sign-in" finds "signin" and أ finds ا. */
export function fold(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[\u0300-\u036f\u064b-\u065f\u0670]/g, '')
    .replace(/[أإآ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .replace(/ة/g, 'ه')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '');
}

/** Whether a page matches the words typed: every word in its name, description or keywords. */
export function matches(query: string, haystack: readonly string[]): boolean {
  const words = query
    .split(/\s+/)
    .map(fold)
    .filter((word) => word !== '');
  if (words.length === 0) return true;
  const text = haystack.map(fold).join(' ');
  return words.every((word) => text.includes(word));
}
