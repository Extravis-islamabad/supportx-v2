// WP-042 (REQ-ADM-106, 107, 108): every setup page, once. The setup home, the setup menu, setup
// search and the command palette all read this map; a test checks that every admin route is in
// it. Labels: `setup.group.<group>`, `nav.admin_<key>` (the page name),
// `setup.page.<key>.description` and `setup.page.<key>.keywords` (comma-separated words and
// synonyms, in each language).

import type { LabelKey } from '@supportx/labels';

export const SETUP_GROUPS = [
  'people_access',
  'service_desk',
  'assets',
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
  /** Other permissions that also open the page. */
  also?: string | readonly string[];
  /**
   * The rights that list the page in the setup menu (and so show Admin), when they differ from
   * the ones that open it: a view right opens some pages read-only (REQ-INT-013, the SLA
   * calendars) but lists none of them; Admin is for a manage or configure right (coordinator,
   * 2026-11-09, option b).
   */
  listedBy?: readonly string[];
}

// The connector categories (backend app/shared/connectors/ports.py ConnectorCategory).
const INTEGRATION_CATEGORIES = [
  'identity',
  'email',
  'collaboration',
  'monitoring',
  'devops',
  'endpoint',
  'telephony',
  'automation',
  'analytics',
  'knowledge',
  'ai',
] as const;

/** The rights that list a page in the menu. */
function listing(page: SetupPage): readonly string[] {
  return page.listedBy ?? opening(page);
}

/** The rights that open a page (read-only for a view right). */
function opening(page: SetupPage): string[] {
  const also =
    page.also === undefined ? [] : typeof page.also === 'string' ? [page.also] : page.also;
  return [page.permission, ...also];
}

export const SETUP_PAGES: readonly SetupPage[] = [
  // View rights (users.view, sites.view, sla.view, integrations.view) open their pages read-only
  // by URL or an in-context link, but only a manage or configure right lists them (listedBy).
  {
    key: 'users',
    group: 'people_access',
    labelKey: 'nav.admin_users',
    permission: 'users.view',
    listedBy: ['users.manage'],
  },
  {
    key: 'organization',
    group: 'people_access',
    labelKey: 'nav.admin_organization',
    permission: 'sites.view',
    listedBy: ['sites.manage', 'groups.manage', 'departments.manage'],
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
  // The asset catalogue (WP-049a): its configure right, or settings.manage for every area.
  {
    key: 'assets',
    group: 'assets',
    labelKey: 'nav.admin_assets',
    permission: 'config.assets',
    also: 'settings.manage',
  },
  {
    key: 'automation',
    group: 'automation_sla',
    labelKey: 'nav.admin_automation',
    permission: 'automation.view',
  },
  { key: 'ai', group: 'automation_sla', labelKey: 'nav.admin_ai', permission: 'ai.manage' },
  {
    key: 'sla',
    group: 'automation_sla',
    labelKey: 'nav.admin_sla',
    permission: 'sla.view',
    listedBy: ['sla.manage'],
  },
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
    // Each connector category's own set-up right lists it (REQ-INT-013).
    listedBy: INTEGRATION_CATEGORIES.map((category) => `integrations.manage_${category}`),
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
export const SETUP_PERMISSIONS: readonly string[] = [...new Set(SETUP_PAGES.flatMap(listing))];

/** Pages listed for this person (the menu, setup home, search), in map order. */
export function pagesFor(can: (permission: string) => boolean): SetupPage[] {
  return SETUP_PAGES.filter((page) => listing(page).some(can));
}

/** Whether this person may open the page at all (read-only included): the setup gate's rule. */
/** Opened with a view right only: the page shows, read-only, and says so (QA10-P3-06). */
export function readOnly(page: SetupPage, can: (permission: string) => boolean): boolean {
  return opens(page, can) && !listing(page).some((permission) => can(permission));
}

export function opens(page: SetupPage, can: (permission: string) => boolean): boolean {
  return opening(page).some(can);
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
