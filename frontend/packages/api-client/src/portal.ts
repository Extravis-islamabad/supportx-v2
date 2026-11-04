import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { api, call } from './client';
import { useSingleFlight } from './incidents';
import type { components } from './schema';

// The portal's incidents for requesters (WP-028): their own records (and any wider reach they
// hold), the forms to report an issue, the public conversation, and the answer to a fix. Every
// response carries requester fields only; live updates come on `t:{tenant}:portal_wi:{id}` and
// the person's own channel, and refetch through these same endpoints.
export type PortalIncident = components['schemas']['PortalIncidentOut'];
export type PortalIncidentPage = components['schemas']['PortalIncidentPage'];
export type PortalIncidentInput = components['schemas']['PortalIncidentIn'];
export type PortalTemplate = components['schemas']['PortalTemplateOut'];
export type PortalEntry = components['schemas']['PortalEntryOut'];
export type PortalStatus = components['schemas']['PortalStatus'];
export type PortalReach = components['schemas']['PortalReach'];
export type PortalState = components['schemas']['PortalState'];

export interface PortalIncidentsQuery {
  reach?: PortalReach;
  state?: PortalState;
  q?: string;
  sort?: string;
  cursor?: string;
}

export const portalKeys = {
  all: ['portal', 'incidents'] as const,
  list: (query: PortalIncidentsQuery) => ['portal', 'incidents', 'list', query] as const,
  detail: (id: string) => ['portal', 'incidents', 'detail', id] as const,
  conversation: (id: string) => ['portal', 'incidents', 'conversation', id] as const,
  templates: ['portal', 'incidents', 'templates'] as const,
};

/** "My requests": pages follow each other (`fetchNextPage`), the shown ones kept meanwhile. */
export function usePortalIncidents(query: Omit<PortalIncidentsQuery, 'cursor'>) {
  return useInfiniteQuery({
    queryKey: portalKeys.list(query),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/portal/incidents', {
          params: { query: { ...query, cursor: pageParam } },
        }),
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.has_more ? (last.next_cursor ?? undefined) : undefined),
    placeholderData: keepPreviousData,
  });
}

export function usePortalIncident(id: string) {
  return useQuery({
    queryKey: portalKeys.detail(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/portal/incidents/{record_id}', { params: { path: { record_id: id } } }),
      ),
  });
}

/** Public replies and notes only, oldest first. */
export function usePortalConversation(id: string) {
  return useQuery({
    queryKey: portalKeys.conversation(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/portal/incidents/{record_id}/conversation', {
          params: { path: { record_id: id } },
        }),
      ),
  });
}

/** The forms the portal offers, with the requester's fields only. */
export function usePortalTemplates() {
  return useQuery({
    queryKey: portalKeys.templates,
    queryFn: () => call(api.GET('/api/v1/portal/incidents/templates')),
    staleTime: 60_000,
  });
}

function useSavedRecord() {
  const queryClient = useQueryClient();
  return (saved: PortalIncident) => {
    queryClient.setQueryData(portalKeys.detail(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: [...portalKeys.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: portalKeys.conversation(saved.id) });
  };
}

/** Report an issue. One Idempotency-Key per form, so a retry never creates two. */
export function useReportIssue() {
  const saved = useSavedRecord();
  const once = useSingleFlight(({ body, key }: { body: PortalIncidentInput; key: string }) =>
    call(
      api.POST('/api/v1/portal/incidents', {
        params: { header: { 'Idempotency-Key': key } },
        body,
      }),
    ),
  );
  return useMutation({ mutationFn: once, onSuccess: saved });
}

/** The requester's reply on their own record (a late one may start a follow-up record). */
export function usePortalReply(id: string) {
  const saved = useSavedRecord();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      call(
        api.POST('/api/v1/portal/incidents/{record_id}/replies', {
          params: { path: { record_id: id } },
          body: { body },
        }),
      ),
    onSuccess: (record) => {
      saved(record);
      void queryClient.invalidateQueries({ queryKey: portalKeys.conversation(id) });
    },
  });
}

/** Confirm the fix (`comment` null) or say it is not fixed (with the requester's words). */
export function useAnswerFix(id: string) {
  const saved = useSavedRecord();
  return useMutation({
    mutationFn: (comment: string | null) =>
      comment === null
        ? call(
            api.POST('/api/v1/portal/incidents/{record_id}/resolution/confirm', {
              params: { path: { record_id: id } },
            }),
          )
        : call(
            api.POST('/api/v1/portal/incidents/{record_id}/resolution/reject', {
              params: { path: { record_id: id } },
              body: { comment },
            }),
          ),
    onSuccess: saved,
  });
}

export type PortalPerson = components['schemas']['PortalPersonOut'];

/** People the signed-in requester may report for (WP-030, REQ-SR-011): names only, in scope. */
export function usePortalOnBehalfPeople(search: string) {
  const text = search.trim();
  return useQuery({
    queryKey: ['portal', 'on-behalf-people', text] as const,
    queryFn: () =>
      call(
        api.GET('/api/v1/portal/incidents/on-behalf-people', {
          params: { query: { search: text } },
        }),
      ),
    enabled: text.length >= 2,
    staleTime: 30_000,
  });
}
