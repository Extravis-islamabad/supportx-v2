import { useMatches } from 'react-router';

import { ComingSoon, NotInPlan, useLicence } from '@supportx/ui';

import { navItem } from '../nav';

/** A sidebar section without its module yet: "coming soon", or "not in your plan". */
export function SectionPage() {
  const matches = useMatches();
  const { has, isAdmin } = useLicence();
  const handle = matches.at(-1)?.handle as { section?: string } | undefined;
  const item = navItem(handle?.section ?? '');
  if (item === undefined) return null;
  if (item.feature !== undefined && !has(item.feature)) {
    return <NotInPlan titleKey={item.labelKey} isAdmin={isAdmin} />;
  }
  return <ComingSoon titleKey={item.labelKey} />;
}
