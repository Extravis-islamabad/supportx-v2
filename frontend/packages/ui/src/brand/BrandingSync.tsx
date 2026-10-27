import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { queryKeys, useBranding, usePublicBranding } from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';

import { useAppearance } from '../appearance';
import { BRANDING_CHANGED, brandingFrom } from './brandingFrom';

/**
 * Before sign-in: the brand of the address in use (subdomain or custom domain), so the waiting
 * and sign-in screens already look like the tenant's (REQ-SEC-003). Renders nothing.
 */
export function AddressBranding() {
  const { setBranding } = useAppearance();
  const found = usePublicBranding();
  useEffect(() => {
    setBranding('address', brandingFrom(found.data));
  }, [found.data, setBranding]);
  return null;
}

/**
 * Signed in: the tenant's brand, reloaded live when an admin saves it (REQ-ADM-055 AC1,
 * REQ-PRT-016 AC1). Inside the realtime provider. Renders nothing.
 */
export function TenantBranding() {
  const { setBranding } = useAppearance();
  const queryClient = useQueryClient();
  const found = useBranding();
  useTenantChannel((event) => {
    if (event.type === BRANDING_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.branding.all });
    }
  });
  useEffect(() => {
    setBranding('tenant', brandingFrom(found.data));
  }, [found.data, setBranding]);
  useEffect(
    () => () => {
      setBranding('tenant', undefined);
    },
    [setBranding],
  );
  return null;
}
