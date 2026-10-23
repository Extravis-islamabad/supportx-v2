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
  /** Permissions that open the section (any one of them, WP-016); none = everyone. */
  permissions?: readonly string[];
}

export interface VisibleNavItem extends NavItem {
  /** Shown to an admin with an upgrade hint, but the section is not in the plan. */
  locked: boolean;
}

/**
 * Which sections a user sees (WP-016): those whose permission they hold. A section outside the
 * tenant's plan is shown locked, with an upgrade hint, to users who manage the licence: they can
 * act on it, while for everyone else a menu of things they cannot open is only noise.
 */
export function visibleNav(
  items: readonly NavItem[],
  {
    canAny,
    has,
    managesLicence,
  }: {
    canAny: (keys: readonly string[]) => boolean;
    has: (feature: Feature) => boolean;
    managesLicence: boolean;
  },
): VisibleNavItem[] {
  const result: VisibleNavItem[] = [];
  for (const item of items) {
    const outsidePlan = item.feature !== undefined && !has(item.feature);
    if (outsidePlan) {
      if (managesLicence) result.push({ ...item, locked: true });
      continue;
    }
    if (item.permissions === undefined || canAny(item.permissions)) {
      result.push({ ...item, locked: false });
    }
  }
  return result;
}
