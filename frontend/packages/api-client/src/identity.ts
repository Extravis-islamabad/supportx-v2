import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-039: Admin › Sign-in and security (identity.manage). Every write is audited server-side.

export type IdentitySettings = components['schemas']['IdentitySettingsOut'];
export type IdentitySettingsInput = components['schemas']['IdentitySettingsBody'];
export type SsoProvider = components['schemas']['SsoOut'];
export type SsoInput = components['schemas']['SsoBody'];
export type SsoTestResult = components['schemas']['SsoTestResultOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** Session timeouts and people creation (version 0: the defaults, never saved). */
export function useIdentitySettings() {
  return useQuery({
    queryKey: queryKeys.identity.settings,
    queryFn: () => call(api.GET('/api/v1/identity/settings')),
    staleTime: 0,
  });
}

/** Save the sign-in settings; refusals come back by field (the screen shows them). */
export function useSaveIdentitySettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: IdentitySettingsInput; version: number }) =>
      call(api.PUT('/api/v1/identity/settings', { params: { header: ifMatch(version) }, body })),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.identity.settings, saved);
    },
  });
}

/** The tenant's single sign-on set-ups. */
export function useSsoProviders() {
  return useQuery({
    queryKey: queryKeys.identity.sso,
    queryFn: () => call(api.GET('/api/v1/identity/sso')),
  });
}

function useSsoChanged() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.sso });
}

/** Add a set-up (checked, saved in draft); `key` is the Idempotency-Key of this attempt. */
export function useCreateSso() {
  const changed = useSsoChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: SsoInput; key: string }) =>
      call(
        api.POST('/api/v1/identity/sso', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: changed,
  });
}

/** Change a set-up (leave `client_secret` out to keep the saved one). */
export function useUpdateSso() {
  const changed = useSsoChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, body, version }: { id: string; body: SsoInput; version: number }) =>
      call(
        api.PUT('/api/v1/identity/sso/{provider_id}', {
          params: { path: { provider_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: changed,
  });
}

/** Switch a set-up on (it needs a passed test) or off. */
export function useSwitchSso() {
  const changed = useSsoChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, on, version }: { id: string; on: boolean; version: number }) =>
      call(
        api.POST(
          on
            ? '/api/v1/identity/sso/{provider_id}/switch-on'
            : '/api/v1/identity/sso/{provider_id}/switch-off',
          { params: { path: { provider_id: id }, header: ifMatch(version) } },
        ),
      ),
    onSuccess: changed,
  });
}

/** Remove a set-up (Keycloak's provider too; the domains only it claimed are given back). */
export function useRemoveSso() {
  const changed = useSsoChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/identity/sso/{provider_id}', {
          params: { path: { provider_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: changed,
  });
}

/** Begin a test sign-in: open `url` in a pop-up, then poll `useSsoTestResult`. */
export function useStartSsoTest() {
  return useMutation({
    meta: { silent: true },
    mutationFn: (id: string) =>
      call(
        api.POST('/api/v1/identity/sso/{provider_id}/tests', {
          params: { path: { provider_id: id } },
        }),
      ),
  });
}

/**
 * A test's result, polled every 2 seconds while pending, and while refused because this browser
 * is signed in as someone else (the admin then runs the test in a private window).
 */
export function useSsoTestResult(id: string, testId: string | null) {
  return useQuery({
    queryKey: queryKeys.identity.test(id, testId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/identity/sso/{provider_id}/tests/{test_id}', {
          params: { path: { provider_id: id, test_id: testId ?? '' } },
        }),
      ),
    enabled: testId !== null,
    refetchInterval: (query) => {
      const found = query.state.data;
      const waiting =
        found?.status === 'pending' || found?.reason === 'signed_in_as_someone_else';
      return waiting ? 2000 : false;
    },
    meta: { silent: true },
  });
}
