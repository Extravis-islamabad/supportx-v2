import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

export type BrandingResult = components['schemas']['BrandingOut'];
export type PublicBrandingResult = components['schemas']['PublicBrandingOut'];
export type BrandingSettings = components['schemas']['BrandingSettingsOut'];
export type BrandingInput = components['schemas']['BrandingIn'];
export type BrandingColourReport = components['schemas']['ColourReportOut'];
export type BrandingCheckCode = components['schemas']['CheckCode'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/**
 * The logo and colours of the address in use (WP-017, REQ-SEC-004): before sign-in the apps show
 * them. Unknown addresses get the default (`customised` false). Never decides access.
 */
export function usePublicBranding(enabled = true) {
  return useQuery({
    queryKey: queryKeys.branding.public,
    queryFn: () => call(api.GET('/api/v1/public/branding')),
    enabled,
    staleTime: 5 * 60_000,
    meta: { silent: true },
  });
}

/** Your tenant's brand (colours, texts, logo URLs) for the console and portal theme. */
export function useBranding(enabled = true) {
  return useQuery({
    queryKey: queryKeys.branding.current,
    queryFn: () => call(api.GET('/api/v1/organization/branding')),
    enabled,
    meta: { silent: true },
  });
}

/** The branding screen's values (`branding.manage`). */
export function useBrandingSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.branding.settings,
    queryFn: () => call(api.GET('/api/v1/organization/branding/settings')),
    enabled,
    staleTime: 0,
  });
}

/** Save the whole branding (version 0 creates it); every open screen follows live. */
export function useSaveBranding() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: BrandingInput; version: number }) =>
      call(
        api.PUT('/api/v1/organization/branding/settings', {
          params: { header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.branding.settings, saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.branding.current });
    },
    onError: (error) => {
      // A stale save: fetch the saved branding, so the conflict dialog can compare (QA WP-029 BUG-05).
      if (error instanceof ApiError && error.isConflict) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.branding.settings });
      }
    },
  });
}

/** WCAG AA checks for colours being chosen, with the nearest passing ones (nothing saved). */
export function useBrandingColourCheck(
  primary: string | null,
  gradient: readonly [string, string] | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.branding.check(primary, gradient),
    queryFn: () =>
      call(
        api.POST('/api/v1/organization/branding/check', {
          body: {
            primary_colour: primary,
            gradient: gradient === null ? null : [gradient[0], gradient[1]],
          },
        }),
      ),
    enabled,
    staleTime: Infinity,
    placeholderData: (previous) => previous,
    meta: { silent: true },
  });
}

export type DomainsResult = components['schemas']['DomainsOut'];
export type CustomDomain = components['schemas']['DomainOut'];

/** The tenant's subdomain and custom domains (`branding.manage`). */
export function useDomains(enabled = true) {
  return useQuery({
    queryKey: queryKeys.branding.domains,
    queryFn: () => call(api.GET('/api/v1/organization/domains')),
    enabled,
  });
}

function useDomainsChanged() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.branding.domains });
}

/** Add a custom domain; `key` is the form's Idempotency-Key. */
export function useAddDomain() {
  const changed = useDomainsChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ host, key }: { host: string; key: string }) =>
      call(
        api.POST('/api/v1/organization/domains', {
          params: { header: { 'Idempotency-Key': key } },
          body: { host },
        }),
      ),
    onSuccess: changed,
  });
}

/** Check now whether the domain points to this installation. */
export function useVerifyDomain() {
  const changed = useDomainsChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: (id: string) =>
      call(
        api.POST('/api/v1/organization/domains/{domain_id}/verify', {
          params: { path: { domain_id: id } },
        }),
      ),
    onSuccess: changed,
  });
}

/** Use the tenant's own certificate for a domain. */
export function useUploadCertificate() {
  const changed = useDomainsChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      certificate,
      privateKey,
    }: {
      id: string;
      version: number;
      certificate: string;
      privateKey: string;
    }) =>
      call(
        api.PUT('/api/v1/organization/domains/{domain_id}/certificate', {
          params: { path: { domain_id: id }, header: ifMatch(version) },
          body: { certificate_pem: certificate, private_key_pem: privateKey },
        }),
      ),
    onSuccess: changed,
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) changed();
    },
  });
}

/** Remove a custom domain: it stops resolving at once. */
export function useRemoveDomain() {
  const changed = useDomainsChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/organization/domains/{domain_id}', {
          params: { path: { domain_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: changed,
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) changed();
    },
  });
}
