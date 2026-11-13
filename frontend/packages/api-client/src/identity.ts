import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { API_BASE, api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-039: Admin › Sign-in and security (identity.manage). Every write is audited server-side.

export type IdentitySettings = components['schemas']['IdentitySettingsOut'];
export type IdentitySettingsInput = components['schemas']['IdentitySettingsBody'];
export type SsoProvider = components['schemas']['SsoOut'];
export type SsoInput = components['schemas']['SsoBody'];
export type SsoTestResult = components['schemas']['SsoTestResultOut'];
export type Invitation = components['schemas']['InvitationOut'];
export type MfaRole = components['schemas']['MfaRoleOut'];
export type MfaMode = MfaRole['mode'];
export type AccountSecurity = components['schemas']['AccountSecurityOut'];
export type AccountAction = 'password' | 'mfa' | 'recovery_codes';
export type NetworkRules = components['schemas']['NetworkRulesOut'];
export type NetworkRulesInput = components['schemas']['NetworkRulesBody'];
export type SignInEvent = components['schemas']['SignInEventOut'];
export type SsoPolicy = components['schemas']['SsoPolicyOut'];
export type SsoPolicyInput = components['schemas']['SsoPolicyBody'];
export type SsoRequired = components['schemas']['SsoRequired'];
export type TenantAdmin = components['schemas']['TenantAdminOut'];
export type BreakGlassInput = components['schemas']['BreakGlassBody'];
export type SignInLogPage = components['schemas']['SignInLogPage'];
export type SignInOutcome = SignInEvent['outcome'];
export type SignInMethod = SignInEvent['method'];

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
    onError: onConflict(
      () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.settings }),
    ),
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

/** A stale change: fetch the saved version, so the conflict dialog can compare (QA WP-029 BUG-05). */
function onConflict(refresh: () => void) {
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) refresh();
  };
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
    onError: onConflict(changed),
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
    onError: onConflict(changed),
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
    onError: onConflict(changed),
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
      const waiting = found?.status === 'pending' || found?.reason === 'signed_in_as_someone_else';
      return waiting ? 2000 : false;
    },
    meta: { silent: true },
  });
}

// --- the password policy (REQ-SEC-005) ---------------------------------------------------------

/** After the worker could not apply the saved policy: ask it to try again. */
export function useApplyPasswordPolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: () => call(api.POST('/api/v1/identity/settings/password-policy/apply')),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.identity.settings, saved);
    },
  });
}

// --- invitations (REQ-SEC-018..020; users.manage) ----------------------------------------------

/** The tenant's newest invitations, or one person's (`userId`). */
export function useInvitations(userId?: string, enabled = true) {
  return useQuery({
    enabled,
    queryKey:
      userId === undefined
        ? queryKeys.identity.invitations
        : queryKeys.identity.personInvitations(userId),
    queryFn: () =>
      call(api.GET('/api/v1/identity/invitations', { params: { query: { user_id: userId } } })),
  });
}

function useInvitationsChanged() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.invitations });
}

/** Invite a person who has not signed in yet; `key` is this attempt's Idempotency-Key. */
export function useInvite() {
  const changed = useInvitationsChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ userId, key }: { userId: string; key: string }) =>
      call(
        api.POST('/api/v1/identity/invitations', {
          params: { header: { 'Idempotency-Key': key } },
          body: { user_id: userId },
        }),
      ),
    onSuccess: changed,
  });
}

/** A new e-mail and a new expiry, or stop the link at once. */
export function useInvitationAction() {
  const changed = useInvitationsChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      action,
    }: {
      id: string;
      version: number;
      action: 'resend' | 'revoke';
    }) =>
      call(
        api.POST(
          action === 'resend'
            ? '/api/v1/identity/invitations/{invitation_id}/resend'
            : '/api/v1/identity/invitations/{invitation_id}/revoke',
          { params: { path: { invitation_id: id }, header: ifMatch(version) } },
        ),
      ),
    onSuccess: changed,
    onError: onConflict(changed),
  });
}

/** Keycloak asks the person for a new password at their next sign-in; their sessions end. */
export function useRequireNewPassword() {
  return useMutation({
    meta: { silent: true },
    mutationFn: (userId: string) =>
      call(
        api.POST('/api/v1/identity/people/{user_id}/require-new-password', {
          params: { path: { user_id: userId } },
        }),
      ),
  });
}

/** "Forgot password?": always accepted, whatever the address (nothing to learn from it). */
export function useRequestPasswordReset() {
  return useMutation({
    meta: { silent: true },
    mutationFn: (email: string) =>
      call(api.POST('/api/v1/auth/password-reset', { body: { email } })),
  });
}

// --- MFA (WP-039 session 3; REQ-SEC-022, 024, 025) ---------------------------------------------

/** Every role's MFA mode and its enrolment counts (identity.manage). */
export function useMfaPolicy() {
  return useQuery({
    queryKey: queryKeys.identity.mfa,
    queryFn: () => call(api.GET('/api/v1/identity/mfa')),
  });
}

/** Off, optional or required for one role (If-Match: 0 while it is still the default). */
export function useSetMfaMode() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ roleId, mode, version }: { roleId: string; mode: MfaMode; version: number }) =>
      call(
        api.PUT('/api/v1/identity/mfa/roles/{role_id}', {
          params: { path: { role_id: roleId }, header: ifMatch(version) },
          body: { mode },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.mfa }),
    onError: onConflict(
      () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.mfa }),
    ),
  });
}

/** Remove a person's authenticator and recovery codes; they set MFA up again (never one's own). */
export function useResetMfa() {
  return useMutation({
    meta: { silent: true },
    mutationFn: (userId: string) =>
      call(
        api.POST('/api/v1/identity/people/{user_id}/reset-mfa', {
          params: { path: { user_id: userId } },
        }),
      ),
  });
}

// --- Signed-in sessions (ADR-044 item 5) ------------------------------------------------------

export type ListedSession = components['schemas']['ListedSessionOut'];

/** Your browsers and devices signed in to this organisation, this one marked `current`. */
export function useMySessions() {
  return useQuery({
    queryKey: queryKeys.identity.mySessions,
    queryFn: () => call(api.GET('/api/v1/auth/sessions')),
  });
}

/** Sign one of your browsers or devices out, now. */
export function useEndMySession() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (id: string) =>
      call(
        api.DELETE('/api/v1/auth/sessions/{listed_id}', { params: { path: { listed_id: id } } }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.identity.mySessions }),
  });
}

/**
 * Sign out of every other browser and device of yours (REQ-SEC-030); this one stays signed in.
 * Answers how many were signed out.
 */
export function useEndOtherSessions() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: () => call(api.POST('/api/v1/auth/sessions/end-others')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.identity.mySessions }),
  });
}

/** A person's signed-in browsers and devices (people admins, users.manage). */
export function usePersonSessions(userId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.identity.personSessions(userId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/identity/people/{user_id}/sessions', {
          params: { path: { user_id: userId ?? '' } },
        }),
      ),
    enabled: userId !== undefined,
  });
}

/** Sign a person out of one browser or device (a lost phone). */
export function useEndPersonSession(userId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (id: string) =>
      call(
        api.DELETE('/api/v1/identity/people/{user_id}/sessions/{listed_id}', {
          params: { path: { user_id: userId, listed_id: id } },
        }),
      ),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.identity.personSessions(userId) }),
  });
}

// --- My account (REQ-SEC-028) -----------------------------------------------------------------

/** How the signed-in person signs in, and their recent sign-ins. */
export function useAccountSecurity() {
  return useQuery({
    queryKey: queryKeys.identity.accountSecurity,
    queryFn: () => call(api.GET('/api/v1/account/security')),
  });
}

/**
 * Where to send the browser to change the password, set MFA up or get new recovery codes on the
 * sign-in service's own pages. It comes back to `returnTo` with `account_action` and `status`.
 */
export function accountActionUrl(action: AccountAction, returnTo: string): string {
  const params = new URLSearchParams({ action, returnTo });
  return `${API_BASE}/auth/account-action?${params.toString()}`;
}

// WP-057 S1a: IP allow-lists (REQ-SEC-034) and the sign-in log (REQ-AUD-015).

/** The tenant's IP allow-lists per app, and the address this browser comes from. */
export function useNetworkRules() {
  return useQuery({
    queryKey: queryKeys.identity.networkRules,
    queryFn: () => call(api.GET('/api/v1/identity/network-rules')),
    staleTime: 0,
  });
}

/** Save all three lists; a list that would shut you out comes back at its field. */
export function useSaveNetworkRules() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: NetworkRulesInput; version: number }) =>
      call(
        api.PUT('/api/v1/identity/network-rules', { params: { header: ifMatch(version) }, body }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.identity.networkRules, saved);
    },
    onError: onConflict(
      () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.networkRules }),
    ),
  });
}

export interface SignInFilters {
  outcome?: SignInOutcome[];
  method?: SignInMethod[];
  user_id?: string;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
}

/** A page of the sign-in log, newest first (each read is audited server-side). */
export function useSignIns(filters: SignInFilters) {
  return useQuery({
    queryKey: queryKeys.identity.signIns({ ...filters }),
    queryFn: () => call(api.GET('/api/v1/identity/sign-ins', { params: { query: filters } })),
  });
}

/** Single sign-on required, MFA after it, and the tenant's admins with their break-glass marks. */
export function useSsoPolicy() {
  return useQuery({
    queryKey: queryKeys.identity.ssoPolicy,
    queryFn: () => call(api.GET('/api/v1/identity/sso-policy')),
    staleTime: 0,
  });
}

/** Save the policy; turning it on without an emergency administrator is refused (409). */
export function useSaveSsoPolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: SsoPolicyInput; version: number }) =>
      call(api.PUT('/api/v1/identity/sso-policy', { params: { header: ifMatch(version) }, body })),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.identity.ssoPolicy, saved);
    },
    onError: onConflict(
      () => void queryClient.invalidateQueries({ queryKey: queryKeys.identity.ssoPolicy }),
    ),
  });
}

/** Name or remove an emergency (break-glass) administrator; the policy is fetched again. */
export function useSetBreakGlass() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      userId,
      body,
      version,
    }: {
      userId: string;
      body: BreakGlassInput;
      version: number;
    }) =>
      call(
        api.PUT('/api/v1/identity/break-glass/{user_id}', {
          params: { path: { user_id: userId }, header: ifMatch(version) },
          body,
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.identity.ssoPolicy }),
  });
}
