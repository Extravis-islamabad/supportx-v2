import { useQuery } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

export type Entitlements = components['schemas']['EntitlementsResponse'];
export type Feature = components['schemas']['Feature'];
export type EntitlementState = components['schemas']['EntitlementState'];

/**
 * GET /entitlements: what the tenant's plan includes, for hiding menus and showing licence
 * notices. Only a reflection: the server enforces every rule itself (architecture.md §13.7).
 * Re-read every few minutes so a grace period or read-only switch shows up without a reload;
 * WP-011 will push `licensing.entitlement.changed` instead.
 */
export function useEntitlements(enabled = true) {
  return useQuery({
    queryKey: queryKeys.entitlements,
    queryFn: () => call(api.GET('/api/v1/entitlements')),
    enabled,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}
