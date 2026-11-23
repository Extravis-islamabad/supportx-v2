import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

// A person's GDPR erasure (D-171, ADR-052): the request, the second admin's approval, the
// mentions report and its redaction. Every rule is the server's (people.erase, a recent sign-in,
// not the requester, a reviewed report); these only read and send. A passage of someone's text
// is fetched on demand only and never kept in the query cache (`fetchPassage`).

type S = components['schemas'];
export type Erasure = S['ErasureOut'];
export type ErasureReport = S['ReportOut'];
export type ErasureState = S['ErasureState'];
export type ErasureReason = S['ErasureReason'];
export type ErasureRequest = S['ErasureIn'];
export type ErasureMention = S['MentionOut'];
export type ErasureMentionsPage = S['MentionsOut'];
export type MentionMatchKind = S['MentionMatchKind'];
export type MentionState = S['MentionState'];

export const ERASURE_STATES = [
  'requested',
  'approved',
  'running',
  'failed',
  'done',
  'rejected',
  'expired',
] as const satisfies readonly ErasureState[];
/** Still open: something may yet happen to it. */
export const OPEN_ERASURE_STATES = ['requested', 'approved', 'running', 'failed'] as const;
export const ERASURE_REASONS = [
  'subject_request',
  'no_longer_needed',
  'consent_withdrawn',
  'legal_obligation',
] as const satisfies readonly ErasureReason[];
/** At most this many mentions per redaction (the server's limit). */
export const REDACT_MAX = 200;

export interface ErasuresQuery {
  states?: readonly ErasureState[];
  personId?: string;
}

export const erasureKeys = {
  all: ['erasures'] as const,
  list: (query: ErasuresQuery) => ['erasures', 'list', query] as const,
  detail: (id: string) => ['erasures', 'detail', id] as const,
  mentions: (id: string) => ['erasures', 'mentions', id] as const,
};

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** GET /erasures: the newest 200, by state or person. */
export function useErasures(query: ErasuresQuery, enabled = true) {
  return useQuery({
    queryKey: erasureKeys.list(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/erasures', {
          params: {
            query: {
              state: query.states === undefined ? undefined : [...query.states],
              person_id: query.personId,
            },
          },
        }),
      ),
    enabled,
  });
}

/** One erasure, with the holdings counted now while it waits for a decision. */
export function useErasure(id: string | undefined) {
  return useQuery({
    queryKey: erasureKeys.detail(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/erasures/{erasure_id}', { params: { path: { erasure_id: id ?? '' } } }),
      ),
    enabled: id !== undefined,
  });
}

/** The mentions report's places, oldest first, by cursor. Codes and IDs only, never text. */
export function useErasureMentions(id: string | undefined, enabled = true) {
  return useInfiniteQuery({
    queryKey: erasureKeys.mentions(id ?? ''),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/erasures/{erasure_id}/mentions', {
          params: {
            path: { erasure_id: id ?? '' },
            query: { cursor: pageParam ?? undefined, limit: 50 },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
    enabled: enabled && id !== undefined,
  });
}

/**
 * The text one mention is in: asked for on demand, never cached (no query key), and the caller
 * drops it when the passage closes. Each view is audited by the server; 404 when your own rights
 * don't let you read that record.
 */
export function fetchPassage(erasureId: string, mentionId: string) {
  return call(
    api.GET('/api/v1/erasures/{erasure_id}/mentions/{mention_id}/passage', {
      params: { path: { erasure_id: erasureId, mention_id: mentionId } },
    }),
  );
}

/** The erasure's decisions and the report's review and redaction; each refreshes the erasure. */
export function useErasureActions(id: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: erasureKeys.detail(id) });
    void queryClient.invalidateQueries({ queryKey: ['erasures', 'list'] });
  };
  const approve = useMutation({
    meta: { silent: true },
    mutationFn: (input: { version: number; confirmName: string }) =>
      call(
        api.POST('/api/v1/erasures/{erasure_id}/approve', {
          params: { header: ifMatch(input.version), path: { erasure_id: id } },
          body: { confirm_name: input.confirmName },
        }),
      ),
    onSettled: refresh,
  });
  const reject = useMutation({
    meta: { silent: true },
    mutationFn: (input: { version: number; reason: string | null }) =>
      call(
        api.POST('/api/v1/erasures/{erasure_id}/reject', {
          params: { header: ifMatch(input.version), path: { erasure_id: id } },
          body: { reason_text: input.reason },
        }),
      ),
    onSettled: refresh,
  });
  const review = useMutation({
    meta: { silent: true },
    mutationFn: (input: { version: number }) =>
      call(
        api.POST('/api/v1/erasures/{erasure_id}/report/reviewed', {
          params: { header: ifMatch(input.version), path: { erasure_id: id } },
        }),
      ),
    onSettled: refresh,
  });
  const redact = useMutation({
    meta: { silent: true },
    mutationFn: (input: { version: number; mentionIds: string[] }) =>
      call(
        api.POST('/api/v1/erasures/{erasure_id}/mentions/redact', {
          params: { header: ifMatch(input.version), path: { erasure_id: id } },
          body: { mention_ids: input.mentionIds },
        }),
      ),
    onSettled: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: erasureKeys.mentions(id) });
    },
  });
  return { approve, reject, review, redact };
}

/** POST /people/{id}/erasure (Idempotency-Key): admin A asks; another admin must approve. */
export function useRequestErasure(personId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (input: { key: string; body: ErasureRequest }) =>
      call(
        api.POST('/api/v1/people/{user_id}/erasure', {
          params: { header: { 'Idempotency-Key': input.key }, path: { user_id: personId } },
          body: input.body,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: erasureKeys.all });
    },
  });
}

export type LegalHold = S['HoldOut'];
export type PersonUpload = S['UploadOut'];

export const holdKeys = {
  detail: (userId: string) => ['erasures', 'legal-hold', userId] as const,
  uploads: (userId: string) => ['erasures', 'uploads', userId] as const,
};

/** GET /people/{id}/legal-hold: whether the person is held, by whom, when and why. */
export function useLegalHold(userId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: holdKeys.detail(userId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/people/{user_id}/legal-hold', {
          params: { path: { user_id: userId ?? '' } },
        }),
      ),
    enabled: enabled && userId !== undefined,
  });
}

/** Put on and lift a legal hold (a recent sign-in, If-Match: the person's version). */
export function useLegalHoldActions(userId: string) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: holdKeys.detail(userId) });
  };
  const hold = useMutation({
    meta: { silent: true },
    mutationFn: (input: { version: number; reason: string }) =>
      call(
        api.PUT('/api/v1/people/{user_id}/legal-hold', {
          params: { header: ifMatch(input.version), path: { user_id: userId } },
          body: { reason: input.reason },
        }),
      ),
    onSettled: refresh,
  });
  const lift = useMutation({
    meta: { silent: true },
    mutationFn: (input: { version: number; reason: string }) =>
      call(
        api.POST('/api/v1/people/{user_id}/legal-hold/lift', {
          params: { header: ifMatch(input.version), path: { user_id: userId } },
          body: { reason: input.reason },
        }),
      ),
    onSettled: refresh,
  });
  return { hold, lift };
}

/** GET /people/{id}/uploads, by cursor: names and types only, never content or links. */
export function usePersonUploads(userId: string | undefined, enabled = true) {
  return useInfiniteQuery({
    queryKey: holdKeys.uploads(userId ?? ''),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/people/{user_id}/uploads', {
          params: {
            path: { user_id: userId ?? '' },
            query: { cursor: pageParam ?? undefined, limit: 50 },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
    enabled: enabled && userId !== undefined,
  });
}
