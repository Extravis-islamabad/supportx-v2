import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call, rememberEtag } from './client';
import { queryKeys } from './keys';
import type { components } from './schema';
import type { FilterExpression } from './users';

export type Announcement = components['schemas']['AnnouncementOut'];
export type AnnouncementPublic = components['schemas']['AnnouncementPublicOut'];
export type AnnouncementListItem = components['schemas']['AnnouncementListItem'];
export type AnnouncementPage = components['schemas']['AnnouncementPage'];
export type AnnouncementInput = components['schemas']['AnnouncementIn'];
export type AnnouncementPatch = components['schemas']['AnnouncementPatch'];
export type AnnouncementAction = components['schemas']['AnnouncementAction'];
export type AnnouncementStatus = components['schemas']['AnnouncementStatus'];
export type AnnouncementSeverity = components['schemas']['AnnouncementSeverity'];
export type AnnouncementAudience = components['schemas']['AnnouncementAudience'];
export type AnnouncementVisibility = components['schemas']['AnnouncementVisibility'];
export type AnnouncementFeed = components['schemas']['FeedOut'];
export type AnnouncementHistoryEntry = components['schemas']['HistoryEntryOut'];
export type AnnouncementSettings = components['schemas']['SettingsOut'];
export type AnnouncementOwnerCandidate = components['schemas']['OwnerCandidateOut'];

/** List parameters the UI controls (the shared filter DSL, a sort, the trash or not). */
export interface AnnouncementsQuery {
  filter?: FilterExpression;
  sort?: string;
  limit?: number;
  trash?: boolean;
}

const path = (id: string) => `/api/v1/announcements/${id}`;
const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/**
 * People who may own an announcement (they may manage announcements), matching `search` by name
 * or email; `include` (the current owner) is always named first. For the owner picker; the API
 * refuses anyone else as owner. Never cached as fresh, so role changes show when it reopens.
 */
export function useAnnouncementOwnerCandidates(
  search: string,
  include: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.announcements.ownerCandidates(search, include),
    queryFn: () =>
      call(
        api.GET('/api/v1/announcements/owner-candidates', {
          params: {
            query: {
              search: search === '' ? undefined : search,
              include: include === null ? undefined : [include],
              limit: 20,
            },
          },
        }),
      ),
    enabled,
    staleTime: 0,
    placeholderData: (previous) => previous,
  });
}

/** Staff list (or the trash), cursor-paged: `fetchNextPage()` follows `next_cursor`. */
export function useAnnouncements(query: AnnouncementsQuery, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.announcements.list(query),
    queryFn: ({ pageParam }) => {
      const params = {
        query: {
          filter: query.filter === undefined ? undefined : JSON.stringify(query.filter),
          sort: query.sort,
          limit: query.limit ?? 50,
          cursor: pageParam ?? undefined,
          include_total: pageParam === null,
        },
      };
      return call(
        query.trash === true
          ? api.GET('/api/v1/announcements/trash', { params })
          : api.GET('/api/v1/announcements', { params }),
      );
    },
    initialPageParam: null as string | null,
    getNextPageParam: (page) => (page.has_more ? page.next_cursor : null),
    enabled,
  });
}

/**
 * One announcement: everything for staff (`kind: 'staff'`), what its audience sees otherwise
 * (`kind: 'public'`). Its ETag is remembered for the next write.
 */
export function useAnnouncement(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.announcements.detail(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/announcements/{announcement_id}', {
          params: { path: { announcement_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
    // A 404 is an answer here (deleted, or not for this user), not a reason to retry.
    retry: false,
  });
}

/** Every save of one announcement, newest first. */
export function useAnnouncementHistory(id: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.announcements.history(id),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/announcements/{announcement_id}/history', {
          params: { path: { announcement_id: id }, query: { cursor: pageParam ?? undefined } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
  });
}

/** What is live for the signed-in user now (banners, portal home), and when that changes. */
export function useAnnouncementFeed(enabled = true) {
  return useQuery({
    queryKey: queryKeys.announcements.feed,
    queryFn: () => call(api.GET('/api/v1/announcements/feed')),
    enabled,
    // Banners are not worth an error message: without them the page still works.
    meta: { silent: true },
  });
}

export function useAnnouncementSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.announcements.settings,
    queryFn: () => call(api.GET('/api/v1/announcements/settings')),
    enabled,
  });
}

/** After any write: the record in the cache, the lists and the feed refetched, the ETag kept. */
function useSaved() {
  const queryClient = useQueryClient();
  return (saved: Announcement) => {
    rememberEtag(path(saved.id), `"${String(saved.version)}"`);
    queryClient.setQueryData(queryKeys.announcements.detail(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.announcements.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.history(saved.id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.feed });
  };
}

/**
 * Create a draft. `key` is the form's Idempotency-Key: the same key for a retried save (timeout,
 * double click) returns the first result instead of creating a second announcement.
 */
export function useCreateAnnouncement() {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true }, // the form shows field errors inline
    mutationFn: ({ body, key }: { body: AnnouncementInput; key: string }) =>
      call(
        api.POST('/api/v1/announcements', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: saved,
  });
}

/** PATCH with If-Match for the version the form was loaded from (409 explains who changed what). */
export function useUpdateAnnouncement(id: string) {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: AnnouncementPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/announcements/{announcement_id}', {
          params: { path: { announcement_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

/** Publish, unpublish, archive or reopen; unpublish and archive take an optional reason. */
export function useAnnouncementAction(id: string) {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      action,
      version,
      reason,
    }: {
      action: AnnouncementAction;
      version: number;
      reason?: string;
    }) => {
      const params = { path: { announcement_id: id }, header: ifMatch(version) };
      const body = reason === undefined || reason.trim() === '' ? undefined : { reason };
      switch (action) {
        case 'publish':
          return call(api.POST('/api/v1/announcements/{announcement_id}/publish', { params }));
        case 'unpublish':
          return call(
            api.POST('/api/v1/announcements/{announcement_id}/unpublish', { params, body }),
          );
        case 'archive':
          return call(
            api.POST('/api/v1/announcements/{announcement_id}/archive', { params, body }),
          );
        case 'reopen':
          return call(api.POST('/api/v1/announcements/{announcement_id}/reopen', { params }));
      }
    },
    onSuccess: saved,
  });
}

export function useDeleteAnnouncement(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (version: number) =>
      call(
        api.DELETE('/api/v1/announcements/{announcement_id}', {
          params: { path: { announcement_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.announcements.detail(id) });
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.announcements.all, 'list'] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.feed });
    },
  });
}

export function useRestoreAnnouncement() {
  const saved = useSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.POST('/api/v1/announcements/{announcement_id}/restore', {
          params: { path: { announcement_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateAnnouncementSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ requireSecond, version }: { requireSecond: boolean; version: number }) =>
      call(
        api.PUT('/api/v1/announcements/settings', {
          params: { header: ifMatch(version) },
          body: { require_second_publisher: requireSecond },
        }),
      ),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.announcements.settings, settings);
      // Who may publish changed: the action buttons of open announcements too.
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.announcements.all, 'detail'] });
    },
  });
}
