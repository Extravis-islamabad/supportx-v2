import type { ReactNode } from 'react';

import type { Feature } from '@supportx/api-client';
import type { LabelKey } from '@supportx/labels';

export interface NavItem {
  key: string;
  path: string;
  labelKey: LabelKey;
  icon?: ReactNode;
  /** Licence feature the section needs (WP-009); none = every edition. */
  feature?: Feature;
  /** Only tenant admins see it. */
  adminOnly?: boolean;
}

export interface VisibleNavItem extends NavItem {
  /** Shown to an admin with an upgrade hint, but the section is not in the plan. */
  locked: boolean;
}

/**
 * Which sections a user sees. Sections outside the plan are hidden for everyone except tenant
 * admins, who see them locked with an upgrade hint: they are the ones who can act on it, while
 * for everyone else a menu of things they cannot open is only noise.
 */
export function visibleNav(
  items: readonly NavItem[],
  { has, isAdmin }: { has: (feature: Feature) => boolean; isAdmin: boolean },
): VisibleNavItem[] {
  return items
    .filter((item) => !item.adminOnly || isAdmin)
    .map((item) => ({ ...item, locked: item.feature !== undefined && !has(item.feature) }))
    .filter((item) => !item.locked || isAdmin);
}
