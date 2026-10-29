import type { KbArticle, KbArticleType, KbLanguage, KbStep, KbTopic } from '@supportx/api-client';

// Knowledge screens (WP-033 session 3a): pure helpers, unit-tested without rendering.

export const LANGUAGES: readonly KbLanguage[] = ['en', 'ar'];

/** The reader's language for articles: Arabic for Arabic and Urdu screens, else English. */
export function articleLanguage(locale: string): KbLanguage {
  return locale === 'ar' || locale === 'ur' ? 'ar' : 'en';
}

/** A topic's name in the language, else in English, else in any language it has. */
export function topicName(topic: Pick<KbTopic, 'names'>, language: KbLanguage): string {
  const names = topic.names as Record<string, string | undefined>;
  return names[language] ?? names.en ?? Object.values(names).find(Boolean) ?? '';
}

/** A custom type's name from the admin, else the built-in label key's text via `t`. */
export function typeName(
  type: KbArticleType | undefined,
  code: string,
  language: KbLanguage,
  t: (key: string) => string,
): string {
  const names = (type?.names ?? {}) as Record<string, string | undefined>;
  return names[language] ?? (type?.builtin === false ? (names.en ?? code) : t(`kb_type.${code}`));
}

export interface TopicNode {
  key: string;
  title: string;
  topic: KbTopic;
  children: TopicNode[];
}

/** The topic tree, parents first and siblings in their order. */
export function topicTree(topics: readonly KbTopic[], language: KbLanguage): TopicNode[] {
  const byParent = new Map<string | null, KbTopic[]>();
  for (const topic of topics) {
    const parent = topics.some((t) => t.id === topic.parent_id) ? topic.parent_id : null;
    byParent.set(parent, [...(byParent.get(parent) ?? []), topic]);
  }
  const build = (parent: string | null): TopicNode[] =>
    (byParent.get(parent) ?? [])
      .slice()
      .sort(
        (a, b) =>
          a.sort_order - b.sort_order ||
          topicName(a, language).localeCompare(topicName(b, language)),
      )
      .map((topic) => ({
        key: topic.id,
        title: topicName(topic, language),
        topic,
        children: build(topic.id),
      }));
  return build(null);
}

/** The names from the top topic down to `id` (the article's place). */
export function topicPath(topics: readonly KbTopic[], id: string, language: KbLanguage): string[] {
  const byId = new Map(topics.map((t) => [t.id, t]));
  const path: string[] = [];
  let current = byId.get(id);
  while (current !== undefined && path.length < 10) {
    path.unshift(topicName(current, language));
    current = current.parent_id === null ? undefined : byId.get(current.parent_id);
  }
  return path;
}

/** The topic and everything below it (a deleted topic takes its subtopics along). */
export function subtreeIds(topics: readonly KbTopic[], id: string): Set<string> {
  const ids = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const topic of topics) {
      if (topic.parent_id !== null && ids.has(topic.parent_id) && !ids.has(topic.id)) {
        ids.add(topic.id);
        grew = true;
      }
    }
  }
  return ids;
}

export type Audience = KbArticle['audience'] & {
  inherited?: boolean;
  tech_all?: boolean;
  tech_groups?: string[];
  requesters?: 'none' | 'all' | 'selected';
  req_groups?: string[];
  req_sites?: string[];
  req_departments?: string[];
};

export interface UnitNames {
  groups: ReadonlyMap<string, string>;
  sites: ReadonlyMap<string, string>;
  departments: ReadonlyMap<string, string>;
}

/**
 * The audience in plain words (REQ-KB-045, 078): who reads it among technicians and requesters.
 * `list` joins names the language's way; a unit that no longer exists is left out.
 */
export function audienceWords(
  audience: Audience,
  units: UnitNames,
  t: (key: string, params?: Record<string, string>) => string,
  list: (items: string[]) => string,
): { technicians: string; requesters: string } {
  const named = (ids: readonly string[] | undefined, names: ReadonlyMap<string, string>) =>
    (ids ?? []).map((id) => names.get(id)).filter((name): name is string => name !== undefined);
  const groups = named(audience.tech_groups, units.groups);
  const technicians =
    audience.tech_all !== false
      ? t('knowledge.audience.all_technicians')
      : groups.length > 0
        ? t('knowledge.audience.groups', { names: list(groups) })
        : t('knowledge.audience.nobody');
  let requesters = t('knowledge.audience.no_requesters');
  if (audience.requesters === 'all') requesters = t('knowledge.audience.all_requesters');
  if (audience.requesters === 'selected') {
    const parts = [
      ...named(audience.req_groups, units.groups),
      ...named(audience.req_sites, units.sites),
      ...named(audience.req_departments, units.departments),
    ];
    requesters =
      parts.length > 0
        ? t('knowledge.audience.requesters_in', { names: list(parts) })
        : t('knowledge.audience.nobody');
  }
  return { technicians, requesters };
}

/** What the article page shows: the language asked for when it exists, else another one. */
export function shownLanguage(
  article: Pick<KbArticle, 'published' | 'drafts' | 'default_language'>,
  wanted: KbLanguage,
): KbLanguage {
  const has = (language: string) =>
    article.published[language] !== undefined || article.drafts[language] !== undefined;
  if (has(wanted)) return wanted;
  if (has(article.default_language)) return article.default_language as KbLanguage;
  return LANGUAGES.find(has) ?? wanted;
}

/** Headings of an article body, for its table of contents (h2-h4, in order). */
export function headings(html: string): { level: number; text: string; index: number }[] {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  return Array.from(doc.body.querySelectorAll('h2, h3, h4')).map((heading, index) => ({
    level: Number(heading.tagName.slice(1)),
    text: heading.textContent.trim(),
    index,
  }));
}

/** A history field in words: `version.ar.status` → "Arabic: status". */
export function historyField(
  field: string,
  t: (key: string, p?: Record<string, string>) => string,
) {
  const match = /^version\.(en|ar)\.(\w+)$/.exec(field);
  if (match !== null) {
    return t(`knowledge.history.version_${match[2] ?? ''}`, {
      language: t(`knowledge.language.${match[1] ?? ''}`),
    });
  }
  return t(`knowledge.field.${field}`);
}

/**
 * Why a step is not available here, as a label key; null when it is. Buttons never vanish:
 * a person who may not use one sees it disabled with the reason (plan §9).
 */
export function stepBlocked(
  step: KbStep | 'delete' | 'edit',
  article: KbArticle,
  language: KbLanguage,
): string | null {
  const draft = article.drafts[language];
  const published = article.published[language];
  switch (step) {
    case 'edit':
      return article.can_edit ? null : 'knowledge.why.not_editor';
    case 'submit':
      if (!article.can_edit) return 'knowledge.why.not_editor';
      if (draft === undefined) return 'knowledge.why.no_draft';
      return draft.status === 'draft' ? null : 'knowledge.why.already_in_review';
    case 'approve':
    case 'reject':
      if (!article.can_approve) return 'knowledge.why.not_approver';
      return draft?.status === 'in_review' ? null : 'knowledge.why.nothing_in_review';
    case 'withdraw':
      if (!article.can_withdraw) return 'knowledge.why.not_withdrawer';
      if (article.withdrawn) return 'knowledge.why.already_withdrawn';
      return published === undefined ? 'knowledge.why.not_published' : null;
    case 'still_correct':
      if (!article.can_edit) return 'knowledge.why.not_editor';
      return published === undefined ? 'knowledge.why.not_published' : null;
    case 'delete':
    case 'restore':
      return null; // the server checks knowledge.delete and answers with the reason
  }
}
