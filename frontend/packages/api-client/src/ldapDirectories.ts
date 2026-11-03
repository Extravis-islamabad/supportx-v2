import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-040 (D-118): Admin › Integrations › Directories, AD/LDAP (integrations.manage_identity).
// The bind password goes in and never comes back (only its type and age). The worker connects
// the directory in the identity service; its state (pending, applied, failed) arrives live on
// `integrations.directories_changed`, which refetches every directory query.

const OFF = new Set([403, 409, 503]);
const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export type LdapDirectory = components['schemas']['LdapDirectoryOut'];
export type LdapDirectoryInput = components['schemas']['LdapDirectoryIn'];

/** Every AD/LDAP directory, with how its connection stands. */
export function useLdapDirectories(enabled = true) {
  return useQuery({
    queryKey: queryKeys.directories.ldap,
    queryFn: () => call(api.GET('/api/v1/integrations/ldap-directories')),
    enabled,
    // Not licensed, a shared realm or AD/LDAP not installed: a fact of this installation, so
    // asking again changes nothing. The screen says which.
    retry: (count: number, error: unknown) =>
      !(error instanceof ApiError && OFF.has(error.status)) && count < 3,
  });
}

function useChanged() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.directories.all });
}

function onConflict(refresh: () => void) {
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) refresh();
  };
}

/** Connect an AD/LDAP directory; `key` is the Idempotency-Key of this attempt. */
export function useCreateLdapDirectory() {
  const changed = useChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: LdapDirectoryInput; key: string }) =>
      call(
        api.POST('/api/v1/integrations/ldap-directories', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: changed,
  });
}

/** Replace its settings (leave `bind_password` out to keep the stored one). */
export function useUpdateLdapDirectory() {
  const changed = useChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      body,
      version,
    }: {
      id: string;
      body: LdapDirectoryInput;
      version: number;
    }) =>
      call(
        api.PUT('/api/v1/integrations/ldap-directories/{directory_id}', {
          params: { path: { directory_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: changed,
    onError: onConflict(changed),
  });
}

/** Disconnect it: its people stay and SupportX keeps them. */
export function useRemoveLdapDirectory() {
  const changed = useChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/integrations/ldap-directories/{directory_id}', {
          params: { path: { directory_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: changed,
    onError: onConflict(changed),
  });
}
