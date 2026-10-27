import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

export type BrandingResult = components['schemas']['BrandingOut'];
export type BrandingSettings = components['schemas']['BrandingSettingsOut'];
export type BrandingInput = components['schemas']['BrandingIn'];
export type BrandingColourReport = components['schemas']['ColourReportOut'];
export type BrandingCheckCode = components['schemas']['CheckCode'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/**
 * The brand of the address in use (WP-017, REQ-SEC-004): before sign-in the apps show it. Unknown
 * addresses get the default (tenant_slug null). Never decides access.
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
