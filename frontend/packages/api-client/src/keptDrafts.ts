import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

// WP-046a S5c (REQ-INC-019): a person's unsent create form, kept sealed on the server. Only
// their own; the browser's tab copy stays the first net. The page follows
// `work_items.draft_changed` on the person's channel (form key and version only).

export type KeptDraft = components['schemas']['KeptDraftOut'];
export type KeptDraftForm = 'incident-new';

export const keptDraftKeys = {
  one: (form: KeptDraftForm) => ['kept-drafts', form] as const,
};

/** Your kept draft of a form, or null when there is none (never an error on screen). */
export function useKeptDraftOnServer(form: KeptDraftForm, enabled = true) {
  return useQuery({
    queryKey: keptDraftKeys.one(form),
    queryFn: async () => {
      const { data, response } = await api.GET('/api/v1/drafts/{form_key}', {
        params: { path: { form_key: form } },
      });
      if (response.status === 404) return null;
      if (data === undefined) throw new Error(`kept draft: ${String(response.status)}`);
      return data;
    },
    enabled,
    retry: false,
    staleTime: Infinity,
    meta: { silent: true }, // the form works without it
  });
}

/** Keep the values (If-Match: the version you have, 0 for a new draft). */
export function useSaveKeptDraft(form: KeptDraftForm) {
  return useMutation({
    meta: { silent: true }, // no "saved" chatter; failures are retried quietly (lane C)
    mutationFn: ({ values, version }: { values: Record<string, unknown>; version: number }) =>
      call(
        api.PUT('/api/v1/drafts/{form_key}', {
          params: { path: { form_key: form }, header: { 'If-Match': `"${String(version)}"` } },
          body: { values },
        }),
      ),
  });
}

/** Discard your kept draft (nothing kept is fine). */
export function useDiscardKeptDraft(form: KeptDraftForm) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: () =>
      call(api.DELETE('/api/v1/drafts/{form_key}', { params: { path: { form_key: form } } })),
    onSettled: () => {
      queryClient.setQueryData(keptDraftKeys.one(form), null);
    },
  });
}
