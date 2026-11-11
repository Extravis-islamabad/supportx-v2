import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { useSingleFlight } from './incidents';
import { queryKeys } from './keys';
import type { components } from './schema';

// The conversation of an incident (WP-020b): replies and notes, followers, mentions, typing,
// personal counters and reply templates. Writes refetch only what they changed; other screens
// hear about it on the record channel (`work_items.conversation_changed`, `…followers_changed`).
export type ConversationEntry = components['schemas']['ConversationEntryOut'];
export type ConversationEntryInput = components['schemas']['ConversationEntryIn'];
export type ConversationAdded = components['schemas']['ConversationAddedOut'];
export type EntryKind = components['schemas']['EntryKind'];
export type Visibility = components['schemas']['Visibility'];
export type ReplyMode = components['schemas']['ReplyMode'];
export type Followers = components['schemas']['FollowersOut'];
export type Follower = components['schemas']['FollowerOut'];
export type Mentionable = components['schemas']['MentionableOut'];
export type PersonalCounter = components['schemas']['CounterOut'];
export type ReplyTemplate = components['schemas']['ReplyTemplateOut'];

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

/** The work-item types whose conversation these hooks serve (UI pass 3: the SR record; WP-045d
 * S2: the change record, REQ-CHG-100). */
export type ConversationBase = 'incidents' | 'service-requests' | 'changes';

/**
 * The same engine route under another type's prefix. The conversation routes are generated
 * once per type with identical shapes, so the incident path's types describe them all; only the
 * prefix changes at run time (as the parts hooks do, WP-044c).
 */
function at<P extends string>(base: ConversationBase, path: P): P {
  return path.replace('/api/v1/incidents/', `/api/v1/${base}/`) as P;
}

/** The record's own query (its counts and first response change with the conversation). */
function detailKey(base: ConversationBase, id: string): readonly unknown[] {
  return base === 'incidents' ? queryKeys.incidents.detail(id) : [base, 'detail', id];
}

/** Replies and notes of one incident, oldest first (staff see private notes, marked). */
export function useIncidentConversation(
  id: string,
  enabled = true,
  base: ConversationBase = 'incidents',
) {
  return useQuery({
    queryKey: queryKeys.incidents.conversation(id),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/{record_id}/conversation'), {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}

/** After a conversation write: the timeline and the record (counts, first response) refetched. */
function useConversationSaved(id: string, base: ConversationBase) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.conversation(id) });
    void queryClient.invalidateQueries({ queryKey: detailKey(base, id) });
    void queryClient.invalidateQueries({
      queryKey: [...queryKeys.incidents.all, 'history', id],
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.followers(id) });
  };
}

/** Reply or add a note. One Idempotency-Key per composer, so a retry never posts twice. */
export function useAddConversationEntry(id: string, base: ConversationBase = 'incidents') {
  const saved = useConversationSaved(id, base);
  const once = useSingleFlight(({ body, key }: { body: ConversationEntryInput; key: string }) =>
    call(
      api.POST(at(base, '/api/v1/incidents/{record_id}/conversation'), {
        params: { path: { record_id: id }, header: { 'Idempotency-Key': key } },
        body,
      }),
    ),
  );
  return useMutation({ meta: { silent: true }, mutationFn: once, onSuccess: saved });
}

/** Make a note public or private (the screen asks first, REQ-INC-061 AC3). */
export function useChangeNoteVisibility(id: string, base: ConversationBase = 'incidents') {
  const saved = useConversationSaved(id, base);
  return useMutation({
    mutationFn: ({
      entryId,
      visibility,
      version,
    }: {
      entryId: string;
      visibility: Visibility;
      version: number;
    }) =>
      call(
        api.PATCH(at(base, '/api/v1/incidents/{record_id}/conversation/{entry_id}'), {
          params: { path: { record_id: id, entry_id: entryId }, header: ifMatch(version) },
          body: { visibility },
        }),
      ),
    onSuccess: saved,
  });
}

export function useIncidentFollowers(
  id: string,
  enabled = true,
  base: ConversationBase = 'incidents',
) {
  return useQuery({
    queryKey: queryKeys.incidents.followers(id),
    queryFn: () =>
      call(
        api.GET(at(base, '/api/v1/incidents/{record_id}/followers'), {
          params: { path: { record_id: id } },
        }),
      ),
    enabled,
  });
}

/** Follow (your own ID) or add someone; unfollow or remove someone. */
export function useFollowerChange(id: string, base: ConversationBase = 'incidents') {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, follow }: { userId: string; follow: boolean }) =>
      call(
        follow
          ? api.PUT(at(base, '/api/v1/incidents/{record_id}/followers/{user_id}'), {
              params: { path: { record_id: id, user_id: userId } },
            })
          : api.DELETE(at(base, '/api/v1/incidents/{record_id}/followers/{user_id}'), {
              params: { path: { record_id: id, user_id: userId } },
            }),
      ),
    onSuccess: (found) => {
      queryClient.setQueryData(queryKeys.incidents.followers(id), found);
      void queryClient.invalidateQueries({ queryKey: detailKey(base, id) });
      void queryClient.invalidateQueries({
        queryKey: [...queryKeys.incidents.all, 'history', id],
      });
    },
  });
}

/** Staff to mention or add as followers, saying whether each may see this incident. */
export function fetchMentionable(
  id: string,
  search: string,
  base: ConversationBase = 'incidents',
): Promise<Mentionable[]> {
  return call(
    api.GET(at(base, '/api/v1/incidents/{record_id}/mentionable'), {
      params: { path: { record_id: id }, query: { search: search || undefined, limit: 8 } },
    }),
  );
}

/** "Someone is writing" on the record channel; failures are ignored (a nicety). */
export function sendTyping(
  id: string,
  state: 'start' | 'stop',
  kind: EntryKind,
  base: ConversationBase = 'incidents',
): void {
  void api
    .POST(at(base, '/api/v1/incidents/{record_id}/typing'), {
      params: { path: { record_id: id } },
      body: { state, kind },
    })
    .catch(() => undefined);
}

/** Overdue, due today, waiting on me, updated by others, unassigned in my groups. */
export function useIncidentCounters(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.counters,
    queryFn: () => call(api.GET('/api/v1/incidents/counters')),
    enabled,
    // Overdue and due today change with the clock, not only with events.
    refetchInterval: 60_000,
  });
}

export function useReplyTemplates(enabled = true) {
  return useQuery({
    queryKey: queryKeys.incidents.replyTemplates,
    queryFn: () => call(api.GET('/api/v1/incidents/reply-templates')),
    enabled,
    staleTime: 60_000,
  });
}

/** Add, change or remove a reply template (settings.manage). */
export function useReplyTemplateChange() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (
      change:
        | { kind: 'create'; name: string; body: string }
        | { kind: 'update'; id: string; version: number; name: string; body: string }
        | { kind: 'delete'; id: string; version: number },
    ): Promise<void> => {
      if (change.kind === 'create') {
        await call(
          api.POST('/api/v1/incidents/reply-templates', {
            body: { name: change.name, body: change.body },
          }),
        );
      } else if (change.kind === 'update') {
        await call(
          api.PUT('/api/v1/incidents/reply-templates/{template_id}', {
            params: { path: { template_id: change.id }, header: ifMatch(change.version) },
            body: { name: change.name, body: change.body },
          }),
        );
      } else {
        await call(
          api.DELETE('/api/v1/incidents/reply-templates/{template_id}', {
            params: { path: { template_id: change.id }, header: ifMatch(change.version) },
          }),
        );
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.replyTemplates });
    },
  });
}
