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
// What GET returns: the article plus the reader's own vote (optional, so writes fit too).
export type KbArticle = components['schemas']['ArticleReadOut'];
export type KbArticleInput = components['schemas']['ArticleIn'];
export type KbArticlePatch = components['schemas']['ArticlePatch'];
export type KbArticleRow = components['schemas']['ArticleRowOut'];
export type KbVersion = components['schemas']['VersionOut'];
export type KbDraftPatch = components['schemas']['DraftPatch'];
export type KbHistoryEntry = components['schemas']['KbHistoryEntryOut'];
export type KbSettings = components['schemas']['KnowledgeSettingsOut'];
export type KbSettingsPatch = components['schemas']['KnowledgeSettingsPatch'];
export type KbArticleTypeInput = components['schemas']['ArticleTypeIn'];
export type KbArticleTypePatch = components['schemas']['ArticleTypePatch'];
export type KbArticleLinks = components['schemas']['ArticleLinksOut'];
export type KbRecordArticles = components['schemas']['RecordArticlesOut'];
export type KbApplied = components['schemas']['AppliedOut'];
export type KbFromRecord = components['schemas']['FromRecordOut'];
export type KbVote = components['schemas']['VoteOut'];
export type KbVoteInput = components['schemas']['VoteIn'];
export type KbScores = components['schemas']['ScoresOut'];
export type KbVoteReason = NonNullable<KbVoteInput['reason']>;
export type KbSnippetPart = components['schemas']['SnippetOut'];
/** Where knowledge goes into: a reply or note everyone on the record reads, or staff only. */
export type KbAudience = 'public' | 'private';
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

/** Knowledge settings with If-Match (REQ-KB-090; prefix and next number, D-120). */
export function useUpdateKbSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ changes, version }: { changes: KbSettingsPatch; version: number }) =>
      call(
        api.PATCH('/api/v1/knowledge/settings', {
          params: { header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.knowledge.settings, saved);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.isConflict) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.settings });
      }
    },
  });
}

/** A new custom article type (D-120). */
export function useCreateKbType() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: KbArticleTypeInput; key: string }) =>
      call(
        api.POST('/api/v1/knowledge/types', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.types });
    },
  });
}

/** Change, retire or restore an article type with If-Match (D-120). */
export function useUpdateKbType() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      code,
      changes,
      version,
    }: {
      code: string;
      changes: KbArticleTypePatch;
      version: number;
    }) =>
      call(
        api.PATCH('/api/v1/knowledge/types/{code}', {
          params: { path: { code }, header: ifMatch(version) },
          body: changes,
        }),
      ),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.types });
    },
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

// --- knowledge on records (WP-033 s4, D-121) -----------------------------------------------------

/** An article's linked records you may open, and how many others (REQ-KB-064). */
export function useKbArticleLinks(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.links(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/knowledge/articles/{article_id}/links', {
          params: { path: { article_id: id } },
        }),
      ),
    enabled,
  });
}

/** A record's linked articles you may read, and how many others. */
export function useKbRecordArticles(recordType: string, recordId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.recordArticles(recordType, recordId),
    queryFn: () =>
      call(
        api.GET('/api/v1/knowledge/records/{record_type}/{record_id}/articles', {
          params: { path: { record_type: recordType, record_id: recordId } },
        }),
      ),
    enabled,
  });
}

function useLinksChanged() {
  const queryClient = useQueryClient();
  return (articleId: string, recordType: string, recordId: string) => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.links(articleId) });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.knowledge.recordArticles(recordType, recordId),
    });
  };
}

/** Link an article to a record (once; linking again changes nothing). */
export function useLinkKbArticle() {
  const changed = useLinksChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      articleId,
      recordType,
      recordId,
      key,
    }: {
      articleId: string;
      recordType: string;
      recordId: string;
      key: string;
    }) =>
      call(
        api.POST('/api/v1/knowledge/articles/{article_id}/links', {
          params: { path: { article_id: articleId }, header: { 'Idempotency-Key': key } },
          body: { record_type: recordType, record_id: recordId },
        }),
      ),
    onSuccess: (_, v) => {
      changed(v.articleId, v.recordType, v.recordId);
    },
  });
}

/** Remove a link (needs edit rights on the article). */
export function useUnlinkKbArticle() {
  const changed = useLinksChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      articleId,
      linkId,
    }: {
      articleId: string;
      linkId: string;
      recordType: string;
      recordId: string;
    }) =>
      call(
        api.DELETE('/api/v1/knowledge/articles/{article_id}/links/{link_id}', {
          params: { path: { article_id: articleId, link_id: linkId } },
        }),
      ),
    onSuccess: (_, v) => {
      changed(v.articleId, v.recordType, v.recordId);
    },
  });
}

/** Before inserting: whether the people the record is for may read the article (the server decides). */
export async function kbApplyCheck(
  articleId: string,
  recordType: string,
  recordId: string,
  audience: KbAudience,
) {
  return call(
    api.GET('/api/v1/knowledge/articles/{article_id}/apply-check', {
      params: {
        path: { article_id: articleId },
        query: { record_type: recordType, record_id: recordId, audience },
      },
    }),
  );
}

/** Insert an article into a reply: its content (images copied into your drafts) or its link. */
export function useApplyKbArticle() {
  const changed = useLinksChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      articleId,
      recordType,
      recordId,
      audience,
      mode,
      language,
    }: {
      articleId: string;
      recordType: string;
      recordId: string;
      audience: KbAudience;
      mode: 'content' | 'link';
      language: KbLanguage;
    }) =>
      call(
        api.POST('/api/v1/knowledge/articles/{article_id}/apply', {
          params: { path: { article_id: articleId } },
          body: { record_type: recordType, record_id: recordId, audience, mode, language },
        }),
      ),
    onSuccess: (_, v) => {
      changed(v.articleId, v.recordType, v.recordId);
    },
  });
}

/** Save a record's resolution as a new knowledge draft (REQ-KB-016). */
export function useKbFromRecord() {
  const queryClient = useQueryClient();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({
      recordType,
      recordId,
      topicId,
      typeCode,
      key,
    }: {
      recordType: string;
      recordId: string;
      topicId: string;
      typeCode: string;
      key: string;
    }) =>
      call(
        api.POST('/api/v1/knowledge/articles/from-record', {
          params: { header: { 'Idempotency-Key': key } },
          body: {
            record_type: recordType,
            record_id: recordId,
            topic_id: topicId,
            type_code: typeCode,
          },
        }),
      ),
    onSuccess: (_, v) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledge.recordArticles(v.recordType, v.recordId),
      });
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.knowledge.all, 'list'] });
    },
  });
}

// --- WP-034 session 1: suggestions and "did this help?" (D-125) ---------------------------------

/** Published articles this reader may read that match the text; nothing under three letters. */
export function useKbSuggestions(text: string, language: KbLanguage, enabled = true) {
  const typed = text.trim();
  return useQuery({
    queryKey: queryKeys.knowledge.suggestions(typed, language),
    queryFn: () =>
      call(
        api.GET('/api/v1/knowledge/suggestions', {
          params: { query: { text: typed, language, limit: 5 } },
        }),
      ),
    enabled: enabled && typed.length >= 3,
    placeholderData: (previous) => previous,
    staleTime: 30_000,
  });
}

/** Scores and feedback, for those who may change or approve the article. */
export function useKbScores(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.knowledge.votes(id),
    queryFn: () =>
      call(
        api.GET('/api/v1/knowledge/articles/{article_id}/votes', {
          params: { path: { article_id: id } },
        }),
      ),
    enabled,
  });
}

/** Say whether the version you read helped; voting again changes your vote. */
export function useKbVote(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: KbVoteInput) =>
      call(
        api.PUT('/api/v1/knowledge/articles/{article_id}/vote', {
          params: { path: { article_id: id } },
          body,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.detail(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.votes(id) });
    },
  });
}
