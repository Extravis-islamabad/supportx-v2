import { Alert, Button, Card, Drawer, Empty, Flex, Grid, List, Space, Tag, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import {
  useKbArticle,
  useKbArticles,
  useKbTopics,
  type KbArticle,
  type KbArticleRow,
  type KbLanguage,
} from '@supportx/api-client';
import { NoAccess, RichTextView, useAccess, useAppearance, useLabel } from '@supportx/ui';

import { ArticleActions } from './ArticleActions';
import { useKnowledgeLive } from './live';
import { articleLanguage, topicPath } from './model';

const DECISIONS = ['approve', 'reject'] as const;
const dirOf = (language: string) => (language === 'ar' ? 'rtl' : 'ltr');

/**
 * The approval inbox (WP-033 3b, D-120): the articles awaiting my approval, each previewed side by
 * side with what readers see now, approved or sent back with a reason. Live: an article someone
 * else decides leaves the queue, and says so instead of vanishing.
 */
export function ApprovalInboxPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const allowed = can('knowledge.approve');
  const language = articleLanguage(locale);
  useKnowledgeLive(allowed);
  const list = useKbArticles({ view: 'awaiting_approval', language }, allowed);
  const topics = useKbTopics(allowed);
  const [params, setParams] = useSearchParams();
  const wide = Grid.useBreakpoint().md ?? true;
  // Articles this screen decided: when one leaves the queue it was us, not someone else.
  const [mine, setMine] = useState<ReadonlySet<string>>(new Set());
  const rows = useMemo(() => list.data ?? [], [list.data]);
  const chosen = params.get('article') ?? (wide ? rows[0]?.id : undefined);

  if (!allowed) return <NoAccess titleKey="knowledge.inbox.title" />;

  const choose = (id: string | undefined) => {
    const next = new URLSearchParams(params);
    if (id === undefined) next.delete('article');
    else next.set('article', id);
    setParams(next, { replace: true });
  };
  const decided = (id: string) => {
    setMine(new Set(mine).add(id));
    const after = rows.filter((row) => row.id !== id);
    choose(wide ? after[0]?.id : undefined);
  };
  const gone =
    chosen !== undefined && list.data !== undefined && !rows.some((r) => r.id === chosen);
  const row = rows.find((r) => r.id === chosen);
  const preview =
    chosen === undefined ? null : gone ? (
      <Alert
        type="info"
        showIcon
        role="status"
        message={
          mine.has(chosen)
            ? t('knowledge.inbox.decided_by_you')
            : t('knowledge.inbox.decided_elsewhere')
        }
        action={
          rows[0] !== undefined && (
            <Button
              size="small"
              onClick={() => {
                choose(rows[0]?.id);
              }}
              data-testid="kb-inbox-next"
            >
              {t('knowledge.inbox.next')}
            </Button>
          )
        }
        data-testid="kb-inbox-gone"
      />
    ) : (
      <Preview
        id={chosen}
        language={(row?.language ?? language) as KbLanguage}
        onDecided={() => {
          decided(chosen);
        }}
      />
    );

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('knowledge.inbox.title')}
        </Typography.Title>
        <Link to="/knowledge">{t('knowledge.inbox.back')}</Link>
      </Flex>
      <Flex gap={16} align="start" vertical={!wide}>
        <Card
          title={t('knowledge.inbox.queue', { n: String(rows.length) })}
          style={{ width: wide ? 360 : '100%', flex: 'none' }}
          data-testid="kb-inbox-queue"
        >
          <List<KbArticleRow>
            loading={list.isPending}
            dataSource={rows}
            locale={{ emptyText: <Empty description={t('knowledge.inbox.empty')} /> }}
            renderItem={(item) => (
              <List.Item
                key={item.id}
                onClick={() => {
                  choose(item.id);
                }}
                style={{
                  cursor: 'pointer',
                  paddingInline: 8,
                  background: item.id === chosen ? 'var(--ant-control-item-bg-active)' : undefined,
                }}
                aria-current={item.id === chosen ? 'true' : undefined}
                data-testid={`kb-inbox-item-${item.display_id}`}
              >
                <Flex vertical gap={2} style={{ minWidth: 0, width: '100%' }}>
                  <Typography.Link
                    ellipsis
                    dir="auto"
                    onClick={() => {
                      choose(item.id);
                    }}
                    lang={item.language}
                  >
                    {item.title}
                  </Typography.Link>
                  <Typography.Text type="secondary" ellipsis>
                    {[
                      item.display_id,
                      ...topicPath(topics.data ?? [], item.topic_id, language),
                    ].join(' · ')}
                  </Typography.Text>
                  {item.author_name != null && (
                    <Typography.Text type="secondary" data-testid="kb-inbox-author">
                      {t('knowledge.inbox.by', { name: item.author_name })}
                    </Typography.Text>
                  )}
                  <Space size={4}>
                    <Tag>{t(`knowledge.language.${item.language}`)}</Tag>
                    <Typography.Text type="secondary">
                      {new Intl.DateTimeFormat(locale, {
                        dateStyle: 'medium',
                        timeStyle: 'short',
                      }).format(new Date(item.updated_at))}
                    </Typography.Text>
                  </Space>
                </Flex>
              </List.Item>
            )}
          />
        </Card>
        {wide ? (
          <div style={{ flex: 1, minWidth: 0 }}>{preview}</div>
        ) : (
          <Drawer
            open={chosen !== undefined}
            onClose={() => {
              choose(undefined);
            }}
            width="100%"
            title={row?.title ?? t('knowledge.inbox.title')}
            data-testid="kb-inbox-drawer"
          >
            {preview}
          </Drawer>
        )}
      </Flex>
    </Space>
  );
}

/** The version under review next to the published one, and the two decisions. */
function Preview({
  id,
  language,
  onDecided,
}: {
  id: string;
  language: KbLanguage;
  onDecided: () => void;
}) {
  const t = useLabel();
  const article = useKbArticle(id);
  const wide = Grid.useBreakpoint().lg ?? true;
  if (article.data === undefined) return <Card loading />;
  const data: KbArticle = article.data;
  const review = data.drafts[language];
  const live = data.published[language];
  return (
    <Card
      title={
        <Space wrap>
          <Typography.Text type="secondary">{data.display_id}</Typography.Text>
          <span dir="auto">{review?.title ?? ''}</span>
        </Space>
      }
      data-testid="kb-inbox-preview"
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          {t('knowledge.inbox.owner', { name: data.owner_name ?? t('knowledge.inbox.unknown') })}
        </Typography.Text>
        {review?.change_note != null && review.change_note !== '' && (
          <Alert
            type="info"
            message={t('knowledge.inbox.note')}
            description={<span dir="auto">{review.change_note}</span>}
            data-testid="kb-inbox-note"
          />
        )}
        {live !== undefined && review !== undefined && live.title !== review.title && (
          <Alert
            type="warning"
            showIcon
            message={t('knowledge.inbox.title_changed', { before: live.title })}
            data-testid="kb-inbox-title-changed"
          />
        )}
        <ArticleActions
          article={data}
          language={language}
          onEdit={() => undefined}
          only={DECISIONS}
          onDecided={onDecided}
        />
        <Flex gap={16} vertical={!wide}>
          <Card
            size="small"
            type="inner"
            title={t('knowledge.inbox.in_review')}
            style={{ flex: 1, minWidth: 0 }}
            data-testid="kb-inbox-review"
          >
            <div dir={dirOf(language)} lang={language}>
              <RichTextView html={review?.body_html ?? null} testId="kb-inbox-review-body" />
            </div>
          </Card>
          <Card
            size="small"
            type="inner"
            title={t('knowledge.inbox.published')}
            style={{ flex: 1, minWidth: 0 }}
            data-testid="kb-inbox-published"
          >
            {live === undefined ? (
              <Typography.Text type="secondary" data-testid="kb-inbox-first">
                {t('knowledge.inbox.first_version')}
              </Typography.Text>
            ) : (
              <div dir={dirOf(language)} lang={language}>
                <RichTextView html={live.body_html} testId="kb-inbox-published-body" />
              </div>
            )}
          </Card>
        </Flex>
      </Space>
    </Card>
  );
}
