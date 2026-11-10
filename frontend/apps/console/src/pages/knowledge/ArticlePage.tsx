import { ReadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Flex,
  List,
  Result,
  Segmented,
  Space,
  Tabs,
  Timeline,
  Typography,
} from 'antd';
import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import {
  ApiError,
  queryKeys,
  useKbArticle,
  useKbHistory,
  useKbTopics,
  useKbTypes,
  useKbVersions,
  useSession,
  type KbArticle,
  type KbLanguage,
} from '@supportx/api-client';
import { useJoinParts, useListFormat } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  EmptyText,
  NoAccess,
  PresenceAvatars,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  RichTextView,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { ArticleActions } from './ArticleActions';
import { ArticleLinks } from './ArticleLinks';
import { ArticleSettings } from './ArticleSettings';
import { AudienceSummary } from './AudienceFields';
import { useKnowledgeLive } from './live';
import {
  articleLanguage,
  headings,
  historyField,
  historyValue,
  LANGUAGES,
  shownLanguage,
  topicPath,
  typeName,
} from './model';
import { ArticleFlags, VersionStatusTag } from './tags';
import { FeedbackPanel, HelpfulPrompt } from './Votes';

/** The article page (REQ-KB-077, 078): live on its own channel `kb:{id}`. */
export function ArticlePage() {
  const t = useLabel();
  const { id } = useParams();
  const { can } = useAccess();
  const article = useKbArticle(id);
  useKnowledgeLive(can('knowledge.view'));
  if (!can('knowledge.view')) return <NoAccess titleKey="nav.knowledge" />;
  if (article.error instanceof ApiError && article.error.status === 404) {
    const withdrawn = article.error.code === 'kb_article_withdrawn';
    return (
      <div data-testid="kb-not-available">
        <Result
          status="404"
          title={t(withdrawn ? 'errors.kb_article_withdrawn' : 'errors.kb_article_not_found')}
          extra={
            <Link to="/knowledge" data-testid="kb-back">
              {t('knowledge.back')}
            </Link>
          }
        />
      </div>
    );
  }
  if (article.data === undefined) return null;
  return <ArticleView article={article.data} reload={() => article.refetch()} />;
}

function ArticleView({ article, reload }: { article: KbArticle; reload: () => Promise<unknown> }) {
  const t = useLabel();
  const navigate = useNavigate();
  const joinParts = useJoinParts();
  const { locale, intlLocale } = useAppearance();
  const queryClient = useQueryClient();
  const me = useSession().data?.user.id ?? null;
  const [wanted, setWanted] = useState<KbLanguage>(articleLanguage(locale));
  const language = shownLanguage(article, wanted);
  const shown = article.published[language] ?? article.drafts[language];
  const draft = article.drafts[language];
  const topics = useKbTopics();
  const types = useKbTypes();
  const body = useRef<HTMLDivElement>(null);
  const [settings, setSettings] = useState(false);

  const viewers = useRecordChannel('kb', article.id, (event) => {
    const cached = queryClient.getQueryData<KbArticle>(queryKeys.knowledge.detail(article.id));
    if (event.version !== undefined && cached !== undefined && event.version < cached.version) {
      return;
    }
    void reload();
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.versions(article.id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.links(article.id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.history(article.id) });
    // A vote anywhere refreshes the score here (REQ-KB-069 AC4).
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.votes(article.id) });
  });

  // The path is part of the screen, so it reads in the screen's language (QA10-P4-35), as the
  // topic tree does, whatever language the article itself is shown in.
  const path = topicPath(topics.data ?? [], article.topic_id, articleLanguage(locale));
  const type = (types.data ?? []).find((row) => row.code === article.type_code);
  const contents = useMemo(() => headings(shown?.body_html ?? ''), [shown?.body_html]);
  const dateFormat = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium' });
  const work = article.can_edit || article.can_approve || article.can_withdraw;

  const jump = (index: number) => {
    body.current?.querySelectorAll('h2, h3, h4')[index]?.scrollIntoView({ block: 'start' });
  };

  const dir = language === 'ar' ? 'rtl' : 'ltr';
  // Template A (D-147): the header and actions in one card, the alerts, then the article and its
  // tabs on the start side and its properties in the panel on the end side.
  return (
    <>
      <RecordPage
        testId="kb-article"
        header={
          <RecordHeader
            icon={<ReadOutlined />}
            kind="article"
            typeLabel={t('knowledge.article')}
            displayId={article.display_id}
            title={shown?.title ?? ''}
            testIds={{ title: 'kb-heading' }}
            renderTitle={(title) => (
              <span dir={dir} lang={language}>
                {title}
              </span>
            )}
            tags={
              <>
                {shown !== undefined && <VersionStatusTag status={shown.status} />}
                {draft !== undefined && article.published[language] !== undefined && (
                  <VersionStatusTag status={draft.status} />
                )}
                <ArticleFlags flags={article} />
              </>
            }
            meta={[
              <span key="path" data-testid="kb-path">
                {joinParts([t('knowledge.title'), ...path], ' › ')}
              </span>,
            ]}
            extra={
              <Flex gap={8} align="center" wrap>
                <PresenceAvatars viewers={viewers} selfUserId={me} />
                <Segmented<KbLanguage>
                  value={language}
                  onChange={setWanted}
                  options={LANGUAGES.map((value) => ({
                    value,
                    label: t(`knowledge.language.${value}`),
                    disabled:
                      article.published[value] === undefined && article.drafts[value] === undefined,
                  }))}
                  data-testid="kb-language"
                />
              </Flex>
            }
          />
        }
        actions={
          work ? (
            <Space wrap>
              <ArticleActions
                article={article}
                language={language}
                onEdit={() => {
                  void navigate(`/knowledge/articles/${article.id}/edit/${language}`);
                }}
              />
              {article.can_edit && (
                <Button
                  onClick={() => {
                    setSettings(true);
                  }}
                  data-testid="kb-settings"
                >
                  {t('knowledge.article_settings')}
                </Button>
              )}
            </Space>
          ) : undefined
        }
        alerts={
          <>
            {language !== wanted && (
              <Alert
                type="info"
                showIcon
                message={t('knowledge.no_translation')}
                data-testid="kb-fallback"
              />
            )}
            {article.withdrawn && (
              <Alert
                type="warning"
                showIcon
                data-testid="kb-withdrawn"
                message={t('knowledge.withdrawn_notice')}
                description={
                  article.withdrawn_reason === null
                    ? undefined
                    : t('history.reason', { reason: article.withdrawn_reason })
                }
              />
            )}
            {draft !== undefined && draft.reject_reason !== null && draft.status === 'draft' && (
              <Alert
                type="warning"
                showIcon
                data-testid="kb-reject-reason"
                message={t('knowledge.sent_back')}
                description={t('history.reason', { reason: draft.reject_reason })}
              />
            )}
          </>
        }
        panel={
          <PropertiesPanel
            testId="kb-panel"
            sections={[
              {
                key: 'properties',
                title: t('layout.properties'),
                children: (
                  <PropertyList
                    items={[
                      {
                        key: 'owner',
                        label: t('knowledge.field.owner_id'),
                        content: article.owner_name ?? t('knowledge.someone'),
                        filled: true,
                      },
                      {
                        key: 'type',
                        label: t('knowledge.field.type_code'),
                        content: typeName(type, article.type_code, language, t),
                        filled: true,
                      },
                      {
                        key: 'review',
                        label: t('knowledge.field.review_on'),
                        content:
                          article.review_on === null
                            ? t('knowledge.never')
                            : dateFormat.format(new Date(article.review_on)),
                        filled: true,
                      },
                      {
                        key: 'expires',
                        label: t('knowledge.field.expires_on'),
                        content:
                          article.expires_on === null
                            ? t('knowledge.never')
                            : dateFormat.format(new Date(article.expires_on)),
                        filled: true,
                      },
                      {
                        key: 'audience',
                        label: t('knowledge.field.audience'),
                        content: (
                          <AudienceSummary audience={article.audience} testId="kb-audience" />
                        ),
                        filled: true,
                      },
                      {
                        key: 'translations',
                        label: t('knowledge.field.translations'),
                        // Never an empty value (QA10-P4-03): "Not set" until a language is out.
                        content: LANGUAGES.some(
                          (value) => article.published[value] !== undefined,
                        ) ? (
                          <Space size={4} wrap>
                            {LANGUAGES.filter(
                              (value) => article.published[value] !== undefined,
                            ).map((value) => (
                              <span key={value}>{t(`knowledge.language.${value}`)}</span>
                            ))}
                          </Space>
                        ) : (
                          t('reports.not_set')
                        ),
                        filled: true,
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        }
      >
        <Flex vertical gap={16} style={{ padding: '16px 8px' }}>
          {contents.length > 1 && (
            <nav aria-label={t('knowledge.contents')} data-testid="kb-toc">
              <Typography.Text strong>{t('knowledge.contents')}</Typography.Text>
              <List
                size="small"
                dataSource={contents}
                renderItem={(item) => (
                  <List.Item style={{ paddingInlineStart: (item.level - 2) * 16 }}>
                    <Button
                      type="link"
                      size="small"
                      onClick={() => {
                        jump(item.index);
                      }}
                    >
                      {item.text}
                    </Button>
                  </List.Item>
                )}
              />
            </nav>
          )}
          <div ref={body} dir={dir} lang={language}>
            <RichTextView html={shown?.body_html ?? null} testId="kb-body" />
          </div>
          {shown?.status === 'published' && <HelpfulPrompt article={article} version={shown} />}
          <Tabs
            data-testid="kb-tabs"
            items={[
              {
                key: 'versions',
                label: t('knowledge.tab.versions'),
                children: <Versions id={article.id} />,
              },
              {
                key: 'history',
                label: t('knowledge.tab.history'),
                children: work ? (
                  <History id={article.id} />
                ) : (
                  <EmptyText>{t('knowledge.history_for_editors')}</EmptyText>
                ),
              },
              {
                key: 'links',
                label: t('knowledge.tab.links'),
                children: <ArticleLinks article={article} />,
              },
              {
                key: 'comments',
                label: t('knowledge.tab.comments'),
                children: <EmptyText>{t('knowledge.comments_later')}</EmptyText>,
              },
              {
                key: 'feedback',
                label: t('knowledge.tab.feedback'),
                children: <FeedbackPanel article={article} />,
              },
            ]}
          />
        </Flex>
      </RecordPage>
      {settings && (
        <ArticleSettings
          article={article}
          language={language}
          onClose={() => {
            setSettings(false);
          }}
        />
      )}
    </>
  );
}

function Versions({ id }: { id: string }) {
  const t = useLabel();
  const { intlLocale } = useAppearance();
  const versions = useKbVersions(id);
  const format = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <List
      size="small"
      data-testid="kb-versions"
      dataSource={versions.data ?? []}
      locale={{ emptyText: <EmptyText>{t('knowledge.no_versions')}</EmptyText> }}
      renderItem={(version) => (
        <List.Item>
          <Space wrap>
            <span>{t('knowledge.version_number', { number: String(version.number) })}</span>
            <span>{t(`knowledge.language.${version.language}`)}</span>
            <VersionStatusTag status={version.status} />
            {version.published_at !== null && (
              <Typography.Text type="secondary">
                {format.format(new Date(version.published_at))}
              </Typography.Text>
            )}
            {version.change_note !== null && (
              <Typography.Text type="secondary" dir="auto">
                {version.change_note}
              </Typography.Text>
            )}
          </Space>
        </List.Item>
      )}
    />
  );
}

function History({ id }: { id: string }) {
  const t = useLabel();
  const { intlLocale } = useAppearance();
  const history = useKbHistory(id);
  const format = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium', timeStyle: 'short' });
  const days = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium', timeZone: 'UTC' });
  const listFormat = useListFormat();
  const list = (items: string[]) => listFormat(items, 'conjunction');
  const entries = history.data?.pages.flatMap((page) => page.items) ?? [];
  if (entries.length === 0) return <EmptyText>{t('knowledge.no_history')}</EmptyText>;
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Timeline
        data-testid="kb-history"
        items={entries.map((entry, index) => ({
          key: String(index),
          children: (
            <Space direction="vertical" size={0}>
              <Typography.Text strong>{t(`change_kind.${entry.kind}`)}</Typography.Text>
              <Typography.Text>
                {t('knowledge.history.by', {
                  name: entry.actor_name ?? t(`change_source.${entry.source}`),
                  when: format.format(new Date(entry.occurred_at)),
                })}
              </Typography.Text>
              {entry.changes.map((change) => {
                // Created: what it started with; later saves: from → to (QA10-P4-04).
                const field = historyField(change.field, t);
                const before = historyValue(change.field, change.old, t, days, list);
                const after = historyValue(change.field, change.new, t, days, list);
                let text = field;
                if (after !== null && (entry.kind === 'created' || change.old == null)) {
                  text = t('knowledge.history.set', { field, value: after });
                } else if (after !== null && before !== null) {
                  text = t('history.change', { field, old: before, new: after });
                }
                return (
                  <Typography.Text key={change.field} type="secondary" dir="auto">
                    {text}
                  </Typography.Text>
                );
              })}
              {entry.reason !== null && (
                <Typography.Text type="secondary" dir="auto">
                  {t('history.reason', { reason: entry.reason })}
                </Typography.Text>
              )}
            </Space>
          ),
        }))}
      />
      {history.hasNextPage && (
        <Button onClick={() => void history.fetchNextPage()}>{t('knowledge.show_more')}</Button>
      )}
    </Space>
  );
}
