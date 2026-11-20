import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

// WP-057 S4c (REQ-SEC-045, D-173, D-177): vendor support grants, the tenant admin's screen.
// The one-time password (the out-of-band path) and the link page's password are answers to a
// mutation only: never a query, never kept by the cache (gcTime 0) and reset by their screens.

export type SupportGrant = components['schemas']['SupportGrantOut'];
export type SupportGrantMade = components['schemas']['SupportGrantMadeOut'];
export type SupportGrantInput = components['schemas']['SupportGrantIn'];
export type SupportActivity = components['schemas']['SupportActivityOut'];
export type SupportLinkOpened = components['schemas']['SupportLinkOpenedOut'];

export const vendorSupportKeys = {
  all: ['vendor-support'] as const,
  grants: ['vendor-support', 'grants'] as const,
  grant: (id: string) => ['vendor-support', 'grants', id] as const,
  activity: (id: string) => ['vendor-support', 'grants', id, 'activity'] as const,
  setting: ['vendor-support', 'setting'] as const,
};

/** Every grant of the tenant: open ones first, then newest first. */
export function useSupportGrants(enabled = true) {
  return useQuery({
    queryKey: vendorSupportKeys.grants,
    queryFn: () => call(api.GET('/api/v1/identity/vendor-support/grants')),
    enabled,
  });
}

/** What a grant's account did, newest first (a tenant admin who may read the audit). */
export function useSupportActivity(id: string | undefined) {
  return useInfiniteQuery({
    queryKey: vendorSupportKeys.activity(id ?? ''),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/identity/vendor-support/grants/{grant_id}/activity', {
          params: {
            path: { grant_id: id ?? '' },
            query: pageParam === undefined ? {} : { cursor: pageParam },
          },
        }),
      ),
    getNextPageParam: (last) => (last.has_more ? (last.next_cursor ?? undefined) : undefined),
    enabled: id !== undefined,
  });
}

/** Whether the tenant never allows vendor support (the opt-out). */
export function useVendorSupportSetting(enabled = true) {
  return useQuery({
    queryKey: vendorSupportKeys.setting,
    queryFn: () => call(api.GET('/api/v1/identity/vendor-support/setting')),
    enabled,
  });
}

/** Turn the opt-out on or off (If-Match; refused while a grant is open). */
export function useSaveVendorSupportSetting() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ neverAllow, version }: { neverAllow: boolean; version: number }) =>
      call(
        api.PUT('/api/v1/identity/vendor-support/setting', {
          params: { header: { 'If-Match': `"${String(version)}"` } },
          body: { never_allow: neverAllow },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: vendorSupportKeys.all }),
  });
}

/**
 * Grant access (Idempotency-Key). The answer may hold the one-time password: it lives in this
 * mutation only (gcTime 0), and the screen resets the mutation when its dialog closes.
 */
export function useCreateSupportGrant() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    gcTime: 0,
    mutationFn: ({ body, key }: { body: SupportGrantInput; key: string }) =>
      call(
        api.POST('/api/v1/identity/vendor-support/grants', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: vendorSupportKeys.grants }),
  });
}

/** More hours, never past 72 from the start (If-Match). */
export function useExtendSupportGrant() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, hours }: { id: string; version: number; hours: number }) =>
      call(
        api.POST('/api/v1/identity/vendor-support/grants/{grant_id}/extend', {
          params: { path: { grant_id: id }, header: { 'If-Match': `"${String(version)}"` } },
          body: { hours },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: vendorSupportKeys.grants }),
  });
}

/** End a grant now: its sessions end at once, its account is removed. */
export function useEndSupportGrant() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id }: { id: string }) =>
      call(
        api.POST('/api/v1/identity/vendor-support/grants/{grant_id}/revoke', {
          params: { path: { grant_id: id } },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: vendorSupportKeys.grants }),
  });
}

/** Send the engineer a new sign-in link (the old one stops working). */
export function useResendSupportLink() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id }: { id: string }) =>
      call(
        api.POST('/api/v1/identity/vendor-support/grants/{grant_id}/resend-link', {
          params: { path: { grant_id: id } },
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: vendorSupportKeys.grants }),
  });
}

/**
 * The engineer's link page: the token goes in the POST body, never a URL (lane B (1)). The
 * answer's password lives in this mutation only (gcTime 0); the page resets it on leave.
 */
export function useOpenSupportLink() {
  return useMutation({
    meta: { silent: true },
    gcTime: 0,
    mutationFn: ({ token, tenant }: { token: string; tenant: string | null }) =>
      call(api.POST('/api/v1/public/vendor-support/open', { body: { token, tenant } })),
  });
}
