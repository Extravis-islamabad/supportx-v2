import { useKnownCi } from '@supportx/api-client';
import { useLicence } from '@supportx/ui';

/**
 * The CI a create form was raised from (`?ci=`, lane B's WP-053 S5c Raise menu), or undefined.
 *
 * Asked for only once the plan is known to include the CMDB: while entitlements load `has()`
 * answers yes, and a CI sent without the feature makes the server refuse the whole create
 * (403 entitlement_required). Unknown or unseen, nothing is linked and nothing is said; the
 * server runs its own link and feature checks again on create.
 */
export function useRaisedFromCi(id: string | null) {
  const { entitlements, has } = useLicence();
  return useKnownCi(id, entitlements !== null && has('cmdb')).data;
}
