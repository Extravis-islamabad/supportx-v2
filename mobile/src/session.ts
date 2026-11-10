import { useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call, isApiError, setCsrfToken, type components } from '@supportx/api-client';

import { useSettings } from './settings';

export type Me = components['schemas']['MeResponse'];

/** Which side of the one app a person gets (D-155). The server still decides every permission. */
export type AppSide = 'technician' | 'requester';

/** Requester-only people get the requester screens, as on the web (D-129); everyone else works. */
export function appSide(me: Me): AppSide {
  const { user } = me;
  if (user.user_type !== 'technician') return 'requester';
  return user.roles.every((role) => role === 'requester') && user.roles.length > 0
    ? 'requester'
    : 'technician';
}

export const ME_KEY = ['mobile', 'me'] as const;

/**
 * The signed-in person, their tenant and the CSRF token for writes. A 401 means the session is
 * over (timed out, signed out elsewhere, deactivated): the app forgets it and asks to sign in.
 */
export function useMe() {
  const session = useSettings((state) => state.session);
  const endSession = useSettings((state) => state.endSession);
  return useQuery({
    queryKey: [...ME_KEY, session],
    enabled: session !== null,
    retry: false,
    queryFn: async (): Promise<Me> => {
      try {
        const me = await call(api.GET('/api/v1/auth/me'));
        setCsrfToken(me.csrf_token);
        return me;
      } catch (error) {
        if (isApiError(error) && error.status === 401) await endSession();
        throw error;
      }
    },
  });
}

/** Sign-out ends the server session and Keycloak's; the phone forgets the ID either way. */
export function useSignOut() {
  const setSession = useSettings((state) => state.setSession);
  const client = useQueryClient();
  return async () => {
    try {
      await call(api.POST('/api/v1/auth/logout'));
    } catch {
      // Offline or already over: the server ends it at its timeout; the phone forgets it now.
    }
    await setSession(null);
    client.clear();
  };
}

/** Switch tenant: a new session ID comes back in the header and is kept (settings.ts). */
export function useSwitchTenant() {
  const client = useQueryClient();
  return async (tenantId: string) => {
    const me = await call(
      api.POST('/api/v1/auth/switch-tenant', { body: { tenant_id: tenantId } }),
    );
    setCsrfToken(me.csrf_token);
    client.clear();
  };
}
