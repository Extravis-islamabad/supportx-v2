import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call, setCsrfToken } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

/** GET /auth/me (generated from the OpenAPI contract, never hand-written). */
export type MeResponse = components['schemas']['MeResponse'];
export type SessionUser = components['schemas']['UserOut'];
export type SessionTenant = components['schemas']['TenantOut'];

/** Load the session; remembers its CSRF token for later state-changing calls. */
export async function fetchMe(): Promise<MeResponse> {
  const me = await call(api.GET('/api/v1/auth/me'));
  setCsrfToken(me.csrf_token);
  return me;
}

/** The current session. A 401 resolves to `null` (not logged in) rather than an error. */
export function useSession() {
  return useQuery({
    queryKey: queryKeys.session,
    queryFn: async (): Promise<MeResponse | null> => {
      try {
        return await fetchMe();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setCsrfToken(null);
          return null;
        }
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}

/** Log out (ends the BFF and Keycloak sessions); the app then asks for a new login. */
export function useLogout(): () => Promise<void> {
  const queryClient = useQueryClient();
  return async () => {
    await call(api.POST('/api/v1/auth/logout'));
    setCsrfToken(null);
    queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== queryKeys.session[0] });
    queryClient.setQueryData(queryKeys.session, null);
  };
}

/**
 * Switch the session to another of the user's tenants (POST /auth/switch-tenant). Every cached
 * query belongs to the old tenant, so the whole cache is dropped and the new session stored.
 */
export function useSwitchTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (tenantId: string) =>
      call(api.POST('/api/v1/auth/switch-tenant', { body: { tenant_id: tenantId } })),
    onSuccess: (me) => {
      setCsrfToken(me.csrf_token);
      // Everything but the session itself (which the app shell observes) is replaced.
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== queryKeys.session[0],
      });
      queryClient.setQueryData(queryKeys.session, me);
    },
  });
}
