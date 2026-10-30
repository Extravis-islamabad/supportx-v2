import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// Knowledge base (WP-033; D-108): topics, articles with versions per language, review.
export type KbTopic = components['schemas']['TopicOut'];
export type KbTopicInput = components['schemas']['TopicIn'];
export type KbTopicPatch = components['schemas']['TopicPatch'];
export type KbArticleType = components['schemas']['ArticleTypeOut'];
export type KbArticle = components['schemas']['ArticleOut'];
export type KbArticleInput = components['schemas']['ArticleIn'];
export type KbArticlePatch = components['schemas']['ArticlePatch'];
export type KbArticleRow = components['schemas']['ArticleRowOut'];
export type KbVersion = components['schemas']['VersionOut'];
export type KbDraftPatch = components['schemas']['DraftPatch'];
export type KbHistoryEntry = components['schemas']['KbHistoryEntryOut'];
export type KbSettings = components['schemas']['KnowledgeSettingsOut'];
export type KbLanguage = 'en' | 'ar';

/** The list views (REQ-KB-077). */
export const KB_VIEWS = [
  'published',
  'my_drafts',
  'in_review',
  'awaiting_approval',
  'review_due',
  'due_today',
  'overdue',
  'expired',
  'withdrawn',
  'trash',
] as const;
export type KbView = (typeof KB_VIEWS)[number];

/** List parameters the UI controls. */
export interface KnowledgeQuery {
  view: KbView;
  language: KbLanguage;
  topicId?: string;
  search?: string;
  typeCode?: string;
  ownerId?: string;
  onlyLanguage?: KbLanguage;
}

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export function useKbTopics(enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.topics,
    queryFn: () => call(api.GET('/api/v1/knowledge/topics')),
    enabled,
  });
}

export function useKbTypes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.types,
    queryFn: () => call(api.GET('/api/v1/knowledge/types')),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useKbArticles(query: KnowledgeQuery, enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.list(query),
    queryFn: () =>
      call(
        api.GET('/api/v1/knowledge/articles', {
          params: {
            query: {
              view: query.view,
              language: query.language,
              topic_id: query.topicId,
              q: query.search === undefined || query.search === '' ? undefined : query.search,
              type_code: query.typeCode,
              owner_id: query.ownerId,
              only_language: query.onlyLanguage,
              limit: 100,
            },
          },
        }),
      ),
    enabled,
    placeholderData: (previous) => previous,
  });
}

/** One article as this reader sees it; a 404 is an answer (hidden, withdrawn, gone). */
export function useKbArticle(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.knowledge.detail(id ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/knowledge/articles/{article_id}', {
          params: { path: { article_id: id ?? '' } },
        }),
      ),
    enabled: id !== undefined,
    retry: false,
  });
}

export function useKbVersions(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.versions(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/knowledge/articles/{article_id}/versions', {
          params: { path: { article_id: id } },
        }),
      ),
    enabled,
  });
}

export function useKbHistory(id: string, enabled = true) {
  return useInfiniteQuery({
    queryKey: queryKeys.knowledge.history(id),
    queryFn: ({ pageParam }) =>
      call(
        api.GET('/api/v1/knowledge/articles/{article_id}/history', {
          params: { path: { article_id: id }, query: { cursor: pageParam ?? undefined } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
  });
}

/** "Awaiting my approval" (the menu badge); refreshed by realtime. */
export function useKbApprovalCount(enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.approvals,
    queryFn: () => call(api.GET('/api/v1/knowledge/approvals/count')),
    enabled,
    meta: { silent: true },
  });
}

export function useKbSettings(enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.settings,
    queryFn: () => call(api.GET('/api/v1/knowledge/settings')),
    enabled,
  });
}

/** After a write: the article in the cache, its lists, versions, history and the count refreshed. */
function useArticleSaved() {
  const queryClient = useQueryClient();
  return (id: string, saved?: KbArticle) => {
    if (saved !== undefined) queryClient.setQueryData(queryKeys.knowledge.detail(id), saved);
    else void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.detail(id) });
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.knowledge.all, 'list'] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.versions(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.history(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.approvals });
  };
}

/** On a 409 the saved article is fetched, so the conflict dialog can compare. */
function useRefetchOnConflict(id: string) {
  const queryClient = useQueryClient();
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.detail(id) });
    }
  };
}

export function useCreateKbArticle() {
  const saved = useArticleSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: KbArticleInput; key: string }) =>
      call(
        api.POST('/api/v1/knowledge/articles', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: (article) => {
      saved(article.id, article);
    },
  });
}

export function useUpdateKbArticle(id: string) {
  const saved = useArticleSaved();
  const onError = useRefetchOnConflict(id);
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: KbArticlePatch; version: number }) =>
      call(
        api.PATCH('/api/v1/knowledge/articles/{article_id}', {
          params: { path: { article_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: (article) => {
      saved(id, article);
    },
    onError,
  });
}

/** Start a draft in a language (a new version from the published one, or a translation). */
export function useNewKbDraft(id: string) {
  const saved = useArticleSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: (language: KbLanguage) =>
      call(
        api.POST('/api/v1/knowledge/articles/{article_id}/drafts/{language}', {
          params: { path: { article_id: id, language } },
        }),
      ),
    onSuccess: () => {
      saved(id);
    },
  });
}

/** Autosave a draft (If-Match on the draft's own version). */
export function useSaveKbDraft(id: string, language: KbLanguage) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: KbDraftPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/knowledge/articles/{article_id}/drafts/{language}', {
          params: { path: { article_id: id, language }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: (draft) => {
      queryClient.setQueryData<KbArticle>(queryKeys.knowledge.detail(id), (article) =>
        article === undefined
          ? article
          : { ...article, drafts: { ...article.drafts, [language]: draft } },
      );
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.knowledge.all, 'list'] });
    },
  });
}

export type KbStep = 'submit' | 'approve' | 'reject' | 'withdraw' | 'still_correct' | 'restore';

/**
 * One review step. `version` is the draft's version for submit, approve and reject, the article's
 * for the others; reject and withdraw need a reason, submit takes an optional note.
 */
export function useKbStep(id: string) {
  const saved = useArticleSaved();
  const onError = useRefetchOnConflict(id);
  return useMutation({
    meta: { silent: true },
    mutationFn: async ({
      step,
      version,
      language = 'en',
      text,
    }: {
      step: KbStep;
      version: number;
      language?: KbLanguage;
      text?: string;
    }) => {
      const article = { path: { article_id: id }, header: ifMatch(version) };
      const draft = { path: { article_id: id, language }, header: ifMatch(version) };
      switch (step) {
        case 'submit':
          await call(
            api.POST('/api/v1/knowledge/articles/{article_id}/drafts/{language}/submit', {
              params: draft,
              body: { note: text === undefined || text.trim() === '' ? null : text },
            }),
          );
          return undefined;
        case 'reject':
          await call(
            api.POST('/api/v1/knowledge/articles/{article_id}/drafts/{language}/reject', {
              params: draft,
              body: { reason: text ?? '' },
            }),
          );
          return undefined;
        case 'approve':
          return call(
            api.POST('/api/v1/knowledge/articles/{article_id}/drafts/{language}/approve', {
              params: draft,
            }),
          );
        case 'withdraw':
          return call(
            api.POST('/api/v1/knowledge/articles/{article_id}/withdraw', {
              params: article,
              body: { reason: text ?? '' },
            }),
          );
        case 'still_correct':
          return call(
            api.POST('/api/v1/knowledge/articles/{article_id}/still-correct', { params: article }),
          );
        case 'restore':
          return call(
            api.POST('/api/v1/knowledge/articles/{article_id}/restore', { params: article }),
          );
      }
    },
    onSuccess: (article) => {
      saved(id, article ?? undefined);
    },
    onError,
  });
}

/** To the trash (restorable). */
export function useDeleteKbArticle(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: (version: number) =>
      call(
        api.DELETE('/api/v1/knowledge/articles/{article_id}', {
          params: { path: { article_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.knowledge.detail(id) });
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.knowledge.all, 'list'] });
    },
  });
}

function useTopicsSaved() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.topics });
    void queryClient.invalidateQueries({ queryKey: [...queryKeys.knowledge.all, 'list'] });
  };
}

export function useCreateKbTopic() {
  const saved = useTopicsSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: KbTopicInput; key: string }) =>
      call(
        api.POST('/api/v1/knowledge/topics', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: saved,
  });
}

export function useUpdateKbTopic() {
  const saved = useTopicsSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      id,
      changes,
      version,
    }: {
      id: string;
      changes: KbTopicPatch;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/knowledge/topics/{topic_id}', {
          params: { path: { topic_id: id }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: saved,
  });
}

/** To the trash with its subtopics; its articles move to `moveTo` first. */
export function useDeleteKbTopic() {
  const saved = useTopicsSaved();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version, moveTo }: { id: string; version: number; moveTo?: string }) =>
      call(
        api.DELETE('/api/v1/knowledge/topics/{topic_id}', {
          params: { path: { topic_id: id }, header: ifMatch(version), query: { move_to: moveTo } },
        }),
      ),
    onSuccess: saved,
  });
}
