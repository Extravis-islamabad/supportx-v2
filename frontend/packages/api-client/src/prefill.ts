import { useQuery } from '@tanstack/react-query';

import { api, call } from './client';

// A create form opened with IDs in its address (REQ-AST-045: raised from an asset). Each ID is
// checked quietly before it fills a field: one that does not exist, or that the person may not
// see, leaves the field empty with no message (lane A's condition); the server still checks
// everything again on submit.

const quiet = { silent: true } as const;

/** The asset, if it exists and the person may see it; else undefined (and nothing shown). */
export function useKnownAsset(id: string | null, enabled = true) {
  return useQuery({
    queryKey: ['prefill', 'asset', id ?? ''] as const,
    queryFn: () =>
      call(api.GET('/api/v1/assets/{asset_id}', { params: { path: { asset_id: id ?? '' } } })),
    enabled: enabled && id !== null && id !== '',
    retry: false,
    meta: quiet,
  });
}

/** The person, if they exist and may be seen; else undefined (and nothing shown). */
export function useKnownUser(id: string | null) {
  return useQuery({
    queryKey: ['prefill', 'user', id ?? ''] as const,
    queryFn: () =>
      call(api.GET('/api/v1/users/{user_id}', { params: { path: { user_id: id ?? '' } } })),
    enabled: id !== null && id !== '',
    retry: false,
    meta: quiet,
  });
}
