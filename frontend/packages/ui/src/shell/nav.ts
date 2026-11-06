import type { ReactNode } from 'react';

import type { Feature, NavLayout } from '@supportx/api-client';
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
/** How a feature outside or inside the plan shows: on, locked with the upgrade hint, or hidden. */
export type FeatureState = 'on' | 'locked' | 'hidden';

/**
 * The one rule for features outside the plan (WP-009; D-044's admin switch joins it here when
 * built): on when in the plan, else locked with the upgrade hint for whoever manages the
 * licence and hidden for everyone else. The nav and every locked screen ask this.
 */
export function featureState(
  feature: Feature,
  { has, managesLicence }: { has: (feature: Feature) => boolean; managesLicence: boolean },
): FeatureState {
  if (has(feature)) return 'on';
  return managesLicence ? 'locked' : 'hidden';
}

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
    const state =
      item.feature === undefined ? 'on' : featureState(item.feature, { has, managesLicence });
    if (state !== 'on') {
      if (state === 'locked') result.push({ ...item, locked: true });
      continue;
    }
    if (item.permissions === undefined || canAny(item.permissions)) {
      result.push({ ...item, locked: false });
    }
  }
  return result;
}

/** The navigation layouts a user can choose (WP-011), in the order they are offered. */
export const NAV_LAYOUTS: readonly NavLayout[] = ['top', 'side', 'side_compact'];
