import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-057 S4a (REQ-SEC-036, REQ-SEC-037): service accounts with an owner, and the key policy's
// impact before it is saved. Service accounts are never people: their own list, api_keys.manage.

export type ServiceAccount = components['schemas']['ServiceAccountOut'];
export type ServiceAccountInput = components['schemas']['ServiceAccountIn'];
export type ServiceAccountPatch = components['schemas']['ServiceAccountPatch'];
export type ServiceAccountRoles = components['schemas']['ServiceRolesOut'];
export type KeyPolicyImpact = components['schemas']['PolicyImpactOut'];

export const serviceAccountKeys = {
  all: ['service-accounts'] as const,
  list: ['service-accounts', 'list'] as const,
  roles: (id: string) => ['service-accounts', 'roles', id] as const,
};

/** Every service identity of the tenant, by name. */
export function useServiceAccounts(enabled = true) {
  return useQuery({
    queryKey: serviceAccountKeys.list,
    queryFn: () => call(api.GET('/api/v1/service-accounts')),
    enabled,
  });
}

/** A service account's roles, and the roles you may give it (the picker). */
export function useServiceAccountRoles(id: string | undefined) {
  return useQuery({
    queryKey: serviceAccountKeys.roles(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/service-accounts/{account_id}/roles', {
          params: { path: { account_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
  });
}

/** Make one (Idempotency-Key: a retried save makes no second account). */
export function useCreateServiceAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: ServiceAccountInput; key: string }) =>
      call(
        api.POST('/api/v1/service-accounts', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: serviceAccountKeys.all }),
  });
}

/** Name, description, owner or active (If-Match; a new owner or state asks for a recent sign-in). */
export function useUpdateServiceAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      version,
      body,
    }: {
      id: string;
      version: number;
      body: ServiceAccountPatch;
    }) =>
      call(
        api.PATCH('/api/v1/service-accounts/{account_id}', {
          params: { path: { account_id: id }, header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: serviceAccountKeys.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.all });
    },
  });
}

/** Give (`held`) or take a role, through the guarded path. */
export function useSetServiceAccountRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, roleId, held }: { id: string; roleId: string; held: boolean }) => {
      const params = { params: { path: { account_id: id, role_id: roleId } } };
      return held
        ? call(api.PUT('/api/v1/service-accounts/{account_id}/roles/{role_id}', params))
        : call(api.DELETE('/api/v1/service-accounts/{account_id}/roles/{role_id}', params));
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: serviceAccountKeys.all }),
  });
}

export interface KeyPolicyDraft {
  key_max_lifetime_days: number;
  keys_require_ip_range: boolean;
  allow_non_expiring_keys: boolean;
  key_unused_days: number;
}

/** How many active keys a proposed policy would flag (never revoke), shown before saving. */
export function useKeyPolicyImpact(draft: KeyPolicyDraft | undefined) {
  return useQuery({
    queryKey: [...queryKeys.apiKeys.all, 'policy-impact', draft] as const,
    queryFn: () => {
      if (draft === undefined) throw new Error('no draft'); // never runs: disabled without one
      return call(api.GET('/api/v1/api-keys/policy-impact', { params: { query: draft } }));
    },
    enabled: draft !== undefined,
    placeholderData: keepPreviousData,
  });
}
