import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  Descriptions,
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
import { useJoinParts } from '@supportx/labels';
import { useRecordChannel } from '@supportx/realtime';
import {
  EmptyText,
  NoAccess,
  PresenceAvatars,
  RichTextView,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { ArticleActions } from './ArticleActions';
import { ArticleSettings } from './ArticleSettings';
import { AudienceSummary } from './AudienceFields';
import { useKnowledgeLive } from './live';
import {
  articleLanguage,
  headings,
  historyField,
  LANGUAGES,
  shownLanguage,
  topicPath,
  typeName,
} from './model';
import { ArticleFlags, VersionStatusTag } from './tags';

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
  const { locale } = useAppearance();
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
    void queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.history(article.id) });
  });

  const path = topicPath(topics.data ?? [], article.topic_id, language);
  const type = (types.data ?? []).find((row) => row.code === article.type_code);
  const contents = useMemo(() => headings(shown?.body_html ?? ''), [shown?.body_html]);
  const dateFormat = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' });
  const work = article.can_edit || article.can_approve || article.can_withdraw;

  const jump = (index: number) => {
    body.current?.querySelectorAll('h2, h3, h4')[index]?.scrollIntoView({ block: 'start' });
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="start" wrap gap={12}>
        <Space direction="vertical" size={4} style={{ minWidth: 0 }}>
          <Typography.Text type="secondary" data-testid="kb-path">
            {joinParts([t('knowledge.title'), ...path], ' › ')}
          </Typography.Text>
          <Typography.Text type="secondary">{article.display_id}</Typography.Text>
          <Typography.Title
            level={1}
            style={{ margin: 0 }}
            dir={language === 'ar' ? 'rtl' : 'ltr'}
            data-testid="kb-heading"
          >
            {shown?.title}
          </Typography.Title>
          <Space size={4} wrap>
            {shown !== undefined && <VersionStatusTag status={shown.status} />}
            {draft !== undefined && article.published[language] !== undefined && (
              <VersionStatusTag status={draft.status} />
            )}
            <ArticleFlags flags={article} />
          </Space>
        </Space>
        <Space direction="vertical" align="end">
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
        </Space>
      </Flex>
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
      {work && (
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
      )}
      {settings && (
        <ArticleSettings
          article={article}
          language={language}
          onClose={() => {
            setSettings(false);
          }}
        />
      )}
      <Flex gap={16} wrap align="start">
        <Space direction="vertical" size="middle" style={{ flex: '3 1 480px', minWidth: 0 }}>
          {contents.length > 1 && (
            <Card size="small" title={t('knowledge.contents')} data-testid="kb-toc">
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
            </Card>
          )}
          <div ref={body} dir={language === 'ar' ? 'rtl' : 'ltr'} lang={language}>
            <RichTextView html={shown?.body_html ?? null} testId="kb-body" />
          </div>
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
                children: <EmptyText>{t('knowledge.links_later')}</EmptyText>,
              },
              {
                key: 'comments',
                label: t('knowledge.tab.comments'),
                children: <EmptyText>{t('knowledge.comments_later')}</EmptyText>,
              },
              {
                key: 'feedback',
                label: t('knowledge.tab.feedback'),
                children: <EmptyText>{t('knowledge.feedback_later')}</EmptyText>,
              },
            ]}
          />
        </Space>
        <Card size="small" style={{ flex: '1 1 260px', minWidth: 0 }} data-testid="kb-panel">
          <Descriptions
            column={1}
            size="small"
            items={[
              {
                key: 'owner',
                label: t('knowledge.field.owner_id'),
                children: article.owner_name ?? t('knowledge.someone'),
              },
              {
                key: 'type',
                label: t('knowledge.field.type_code'),
                children: typeName(type, article.type_code, language, t),
              },
              {
                key: 'review',
                label: t('knowledge.field.review_on'),
                children:
                  article.review_on === null
                    ? t('knowledge.never')
                    : dateFormat.format(new Date(article.review_on)),
              },
              {
                key: 'expires',
                label: t('knowledge.field.expires_on'),
                children:
                  article.expires_on === null
                    ? t('knowledge.never')
                    : dateFormat.format(new Date(article.expires_on)),
              },
              {
                key: 'audience',
                label: t('knowledge.field.audience'),
                children: <AudienceSummary audience={article.audience} testId="kb-audience" />,
              },
              {
                key: 'translations',
                label: t('knowledge.field.translations'),
                children: (
                  <Space size={4} wrap>
                    {LANGUAGES.filter((value) => article.published[value] !== undefined).map(
                      (value) => (
                        <span key={value}>{t(`knowledge.language.${value}`)}</span>
                      ),
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      </Flex>
    </Space>
  );
}

function Versions({ id }: { id: string }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const versions = useKbVersions(id);
  const format = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
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
  const { locale } = useAppearance();
  const history = useKbHistory(id);
  const format = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
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
              <Typography.Text>
                {t('knowledge.history.by', {
                  name: entry.actor_name ?? t(`change_source.${entry.source}`),
                  when: format.format(new Date(entry.occurred_at)),
                })}
              </Typography.Text>
              {entry.changes.map((change) => (
                <Typography.Text key={change.field} type="secondary">
                  {historyField(change.field, t)}
                </Typography.Text>
              ))}
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
