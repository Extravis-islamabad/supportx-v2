import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-041 (D-128): API keys. The key text comes back once, in the create answer, and is never
// stored by the browser beyond the dialog that shows it.

export type ApiKey = components['schemas']['ApiKeyOut'];
export type ApiKeyCreated = components['schemas']['ApiKeyCreatedOut'];
export type ApiKeyInput = components['schemas']['ApiKeyIn'];
export type ApiKeyScope = components['schemas']['ScopeOut'];
export type ApiKeyRules = components['schemas']['KeyRulesOut'];

/** Every key for key managers; your own keys for everyone else (the server decides). */
export function useApiKeys(enabled = true) {
  return useQuery({
    queryKey: queryKeys.apiKeys.list,
    queryFn: () => call(api.GET('/api/v1/api-keys')),
    enabled,
  });
}

/** What the key screens may offer the signed-in person. */
export function useApiKeyRules() {
  return useQuery({
    queryKey: queryKeys.apiKeys.rules,
    queryFn: () => call(api.GET('/api/v1/api-keys/rules')),
  });
}

/** The scopes a key may carry: read and write per area. */
export function useApiKeyScopes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.apiKeys.scopes,
    queryFn: () => call(api.GET('/api/v1/api-keys/scopes')),
    staleTime: Infinity,
    enabled,
  });
}

/**
 * Make a key. `key` is the form's Idempotency-Key: a retried save makes no second key (and its
 * answer has no key text, which is never stored anywhere).
 */
export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true }, // the form shows field errors inline
    mutationFn: ({ body, key }: { body: ApiKeyInput; key: string }) =>
      call(api.POST('/api/v1/api-keys', { params: { header: { 'Idempotency-Key': key } }, body })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.list }),
  });
}

/** Revoke at once: the key's next call is refused. */
export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      call(api.POST('/api/v1/api-keys/{key_id}/revoke', { params: { path: { key_id: id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys.list }),
  });
}
