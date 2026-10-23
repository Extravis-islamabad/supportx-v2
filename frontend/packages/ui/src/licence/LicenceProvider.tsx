import { useMemo, type ReactNode } from 'react';

import { useEntitlements, type Feature, type MeResponse } from '@supportx/api-client';

import { LicenceContext, type Licence } from './context';

/**
 * Loads GET /entitlements once per session/tenant and shares it. Until it has loaded nothing is
 * hidden or disabled: the UI never invents a restriction the server has not stated.
 */
export function LicenceProvider({
  session,
  children,
}: {
  session: MeResponse;
  children: ReactNode;
}) {
  const { data } = useEntitlements();
  // Licence notices are for whoever manages the licence (WP-016 permission).
  const isAdmin = (session.permissions ?? []).some((p) => p.key === 'licence.manage');
  const licence = useMemo<Licence>(() => {
    const features = data === undefined ? null : new Set<Feature>(data.features);
    return {
      entitlements: data ?? null,
      has: (feature) => features === null || features.has(feature),
      writable: data?.writable ?? true,
      isAdmin,
    };
  }, [data, isAdmin]);
  return <LicenceContext.Provider value={licence}>{children}</LicenceContext.Provider>;
}
