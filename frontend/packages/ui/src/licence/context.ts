import { createContext, useContext } from 'react';

import type { Entitlements, Feature } from '@supportx/api-client';

export interface Licence {
  /** null while loading (or if the request failed): the UI then assumes nothing is missing. */
  entitlements: Entitlements | null;
  has: (feature: Feature) => boolean;
  /** False in read-only mode: edit actions are disabled (the server refuses them anyway). */
  writable: boolean;
  isAdmin: boolean;
}

export const LicenceContext = createContext<Licence>({
  entitlements: null,
  has: () => true,
  writable: true,
  isAdmin: false,
});

/** What the tenant's plan allows, for showing and hiding UI. The server enforces it. */
export function useLicence(): Licence {
  return useContext(LicenceContext);
}
