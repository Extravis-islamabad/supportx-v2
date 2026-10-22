import { useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, apiGet, apiPost, setCsrfToken } from './http';
import type { components } from './schema';

/** GET /auth/me (generated from the OpenAPI contract, never hand-written). */
export type MeResponse = components['schemas']['MeResponse'];
export type SessionUser = components['schemas']['UserOut'];
export type SessionTenant = components['schemas']['TenantOut'];

export const SESSION_QUERY_KEY = ['auth', 'me'] as const;

/** Load the session; remembers its CSRF token for later state-changing calls. */
export async function fetchMe(): Promise<MeResponse> {
  const me = await apiGet<MeResponse>('/auth/me');
  setCsrfToken(me.csrf_token);
  return me;
}

/** The current session. A 401 resolves to `null` (not logged in) rather than an error. */
export function useSession() {
  return useQuery({
    queryKey: SESSION_QUERY_KEY,
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

/** Log out (ends the BFF and Keycloak sessions), then reload the app, which asks for a new login. */
export function useLogout(): () => Promise<void> {
  const queryClient = useQueryClient();
  return async () => {
    await apiPost('/auth/logout');
    setCsrfToken(null);
    queryClient.setQueryData(SESSION_QUERY_KEY, null);
  };
}
