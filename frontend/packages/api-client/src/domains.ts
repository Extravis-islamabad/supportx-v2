import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-057 S5d (REQ-SEC-010): verified e-mail domains. The TXT record's value is in the add
// answer only (gcTime 0); the screen shows it once and resets the mutation when its dialog closes.

export type VerifiedDomain = components['schemas']['VerifiedDomainOut'];
export type VerifiedDomainAdded = components['schemas']['VerifiedDomainAddedOut'];
export type DomainCheck = components['schemas']['DomainCheckOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** The tenant's domains (identity.manage). */
export function useVerifiedDomains(enabled = true) {
  return useQuery({
    queryKey: queryKeys.identity.domains,
    queryFn: () => call(api.GET('/api/v1/identity/domains')),
    enabled,
  });
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.domains });
}

/** Add one (Idempotency-Key); the record to publish is in this answer only. */
export function useAddVerifiedDomain() {
  const refresh = useRefresh();
  return useMutation({
    meta: { silent: true },
    gcTime: 0,
    mutationFn: ({ domain, key }: { domain: string; key: string }) =>
      call(
        api.POST('/api/v1/identity/domains', {
          params: { header: { 'Idempotency-Key': key } },
          body: { domain },
        }),
      ),
    onSettled: refresh,
  });
}

/** Look for the record now; the outcome is a code (`domain_check.<outcome>`). */
export function useCheckVerifiedDomain() {
  const refresh = useRefresh();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id }: { id: string }) =>
      call(
        api.POST('/api/v1/identity/domains/{domain_id}/check', {
          params: { path: { domain_id: id } },
        }),
      ),
    onSettled: refresh,
  });
}

/** Verify without DNS (no DNS to ask), with a reason; audited. */
export function useVerifyDomainManually() {
  const refresh = useRefresh();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, reason }: { id: string; version: number; reason: string }) =>
      call(
        api.POST('/api/v1/identity/domains/{domain_id}/verify', {
          params: { path: { domain_id: id }, header: ifMatch(version) },
          body: { reason },
        }),
      ),
    onSettled: refresh,
  });
}

/** Remove one, and its sign-in routing. */
export function useRemoveVerifiedDomain() {
  const refresh = useRefresh();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/identity/domains/{domain_id}', {
          params: { path: { domain_id: id }, header: ifMatch(version) },
        }),
      ),
    onSettled: refresh,
  });
}
