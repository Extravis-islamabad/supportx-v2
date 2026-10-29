import { DeleteOutlined, EditOutlined, FolderAddOutlined, PlusOutlined } from '@ant-design/icons';
import { Badge, Button, Card, Flex, Input, Select, Space, Table, Tree, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  KB_VIEWS,
  useKbApprovalCount,
  useKbArticles,
  useKbTopics,
  useKbTypes,
  type KbArticleRow,
  type KbLanguage,
  type KbTopic,
  type KbView,
} from '@supportx/api-client';
import { EmptyText, NoAccess, useAccess, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { useKnowledgeLive } from './live';
import { ArticleFlags, VersionStatusTag } from './tags';
import { DeleteTopicDialog, TopicDialog } from './TopicDialogs';
import { articleLanguage, topicName, topicTree, typeName } from './model';

const SEARCH_DELAY_MS = 300;
// Views for those who work on articles; readers only have "published".
const STAFF_VIEWS: readonly KbView[] = KB_VIEWS;

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return debounced;
}

/**
 * Knowledge (REQ-KB-077): the topic tree beside the article list, with views, filters and search
 * (the search port, WP-027). Live: lists, topics and the approval count refetch on change.
 */
export function KnowledgePage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const allowed = can('knowledge.view');
  const language: KbLanguage = articleLanguage(locale);
  const [params, setParams] = useSearchParams();
  const view = (params.get('view') ?? 'published') as KbView;
  const topicId = params.get('topic') ?? undefined;
  const [search, setSearch] = useState('');
  const [typeCode, setTypeCode] = useState<string>();
  const [onlyLanguage, setOnlyLanguage] = useState<KbLanguage>();
  const text = useDebounced(search.trim(), SEARCH_DELAY_MS);
  const staff = can('knowledge.create') || can('knowledge.approve') || can('knowledge.edit_any');

  const topics = useKbTopics(allowed);
  const types = useKbTypes(allowed);
  const count = useKbApprovalCount(allowed && staff);
  const list = useKbArticles(
    { view, language, topicId, search: text, typeCode, onlyLanguage },
    allowed,
  );
  useKnowledgeLive(allowed);

  const [editing, setEditing] = useState<{ topic: KbTopic | null; parentId: string | null }>();
  const [deleting, setDeleting] = useState<KbTopic | null>(null);
  const allTopics = useMemo(() => topics.data ?? [], [topics.data]);
  const tree = useMemo(() => topicTree(allTopics, language), [allTopics, language]);
  const selected = allTopics.find((topic) => topic.id === topicId);
  const typeByCode = new Map((types.data ?? []).map((type) => [type.code, type]));
  const topicById = new Map(allTopics.map((topic) => [topic.id, topic]));
  const dateFormat = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' });

  if (!allowed) return <NoAccess titleKey="nav.knowledge" />;

  const setParam = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value === undefined) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };
  const awaiting = count.data?.count ?? 0;
  const viewOptions = (staff ? STAFF_VIEWS : (['published'] as const)).map((value) => ({
    value,
    label:
      value === 'awaiting_approval' ? (
        <Space size={6}>
          {t(`kb_view.${value}`)}
          <Badge count={awaiting} size="small" data-testid="kb-awaiting-count" />
        </Space>
      ) : (
        t(`kb_view.${value}`)
      ),
    'aria-label':
      value === 'awaiting_approval'
        ? t('knowledge.awaiting_with_count', { n: String(awaiting) })
        : t(`kb_view.${value}`),
  }));
  const any = { value: '', label: t('users.any') };
  const manageTopics = can('knowledge.manage_topics');
  const articleCount = (topic: KbTopic) =>
    (list.data ?? []).filter((row) => row.topic_id === topic.id).length;

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="center" wrap gap={12}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {t('knowledge.title')}
        </Typography.Title>
        {can('knowledge.create') && (
          <WriteButton
            type="primary"
            icon={<PlusOutlined />}
            onClick={() =>
              void navigate(`/knowledge/articles/new${topicId ? `?topic=${topicId}` : ''}`)
            }
            data-testid="kb-new-article"
          >
            {t('knowledge.new_article')}
          </WriteButton>
        )}
      </Flex>
      <Flex gap={16} wrap align="start">
        <Card
          size="small"
          title={t('knowledge.topics')}
          style={{ flex: '1 1 240px', maxWidth: 360, minWidth: 0 }}
          extra={
            manageTopics && (
              <WriteButton
                size="small"
                icon={<FolderAddOutlined />}
                onClick={() => {
                  setEditing({ topic: null, parentId: topicId ?? null });
                }}
                data-testid="kb-new-topic"
              >
                {t('knowledge.new_topic')}
              </WriteButton>
            )
          }
        >
          <Button
            type={topicId === undefined ? 'link' : 'text'}
            onClick={() => {
              setParam('topic', undefined);
            }}
            data-testid="kb-all-topics"
            style={{ paddingInline: 0 }}
          >
            {t('knowledge.all_topics')}
          </Button>
          {tree.length === 0 ? (
            <EmptyText>{t('knowledge.no_topics')}</EmptyText>
          ) : (
            <Tree
              blockNode
              defaultExpandAll
              selectedKeys={topicId === undefined ? [] : [topicId]}
              treeData={tree}
              onSelect={(keys) => {
                const [key] = keys;
                setParam('topic', key === undefined ? undefined : String(key));
              }}
              data-testid="kb-tree"
            />
          )}
          {manageTopics && selected !== undefined && (
            <Space wrap style={{ marginTop: 8 }}>
              <WriteButton
                size="small"
                icon={<EditOutlined />}
                onClick={() => {
                  setEditing({ topic: selected, parentId: selected.parent_id });
                }}
                data-testid="kb-edit-topic"
              >
                {t('knowledge.edit_topic')}
              </WriteButton>
              <WriteButton
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => {
                  setDeleting(selected);
                }}
                data-testid="kb-delete-topic"
              >
                {t('knowledge.delete_topic')}
              </WriteButton>
            </Space>
          )}
        </Card>
        <Space direction="vertical" size="small" style={{ flex: '3 1 480px', minWidth: 0 }}>
          <Flex gap={12} wrap>
            <Select<KbView>
              aria-label={t('knowledge.view')}
              prefix={`${t('knowledge.view')}:`}
              value={view}
              onChange={(value) => {
                setParam('view', value === 'published' ? undefined : value);
              }}
              options={viewOptions}
              style={{ minWidth: 240 }}
              data-testid="kb-view"
            />
            <Input.Search
              allowClear
              aria-label={t('knowledge.search')}
              placeholder={t('knowledge.search')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              style={{ maxWidth: 320 }}
              data-testid="kb-search"
            />
            <Select
              aria-label={t('knowledge.field.type_code')}
              prefix={`${t('knowledge.field.type_code')}:`}
              value={typeCode ?? ''}
              onChange={(value) => {
                setTypeCode(value === '' ? undefined : value);
              }}
              options={[
                any,
                ...(types.data ?? [])
                  .filter((type) => !type.retired)
                  .map((type) => ({
                    value: type.code,
                    label: typeName(type, type.code, language, t),
                  })),
              ]}
              style={{ minWidth: 180 }}
              data-testid="kb-filter-type"
            />
            <Select
              aria-label={t('knowledge.field.language')}
              prefix={`${t('knowledge.field.language')}:`}
              value={onlyLanguage ?? ''}
              onChange={(value) => {
                setOnlyLanguage(value === '' ? undefined : (value as KbLanguage));
              }}
              options={[
                any,
                ...(['en', 'ar'] as const).map((value) => ({
                  value,
                  label: t(`knowledge.language.${value}`),
                })),
              ]}
              style={{ minWidth: 160 }}
              data-testid="kb-filter-language"
            />
          </Flex>
          <Table<KbArticleRow>
            rowKey="id"
            data-testid="kb-table"
            loading={list.isPending && list.fetchStatus === 'fetching'}
            dataSource={list.data ?? []}
            pagination={false}
            scroll={{ x: 'max-content' }}
            locale={{ emptyText: <EmptyText>{t(`knowledge.empty.${view}`)}</EmptyText> }}
            columns={[
              {
                key: 'display_id',
                title: t('knowledge.field.display_id'),
                dataIndex: 'display_id',
                width: 110,
              },
              {
                key: 'title',
                title: t('knowledge.field.title'),
                render: (_, row) => (
                  <Space direction="vertical" size={2}>
                    <Link
                      to={`/knowledge/articles/${row.id}`}
                      data-testid="kb-row-link"
                      dir={row.language === 'ar' ? 'rtl' : undefined}
                    >
                      {row.title}
                    </Link>
                    <ArticleFlags flags={row} />
                  </Space>
                ),
              },
              {
                key: 'topic',
                title: t('knowledge.field.topic_id'),
                render: (_, row) => {
                  const topic = topicById.get(row.topic_id);
                  return topic === undefined ? null : topicName(topic, language);
                },
              },
              {
                key: 'type',
                title: t('knowledge.field.type_code'),
                render: (_, row) =>
                  typeName(typeByCode.get(row.type_code), row.type_code, language, t),
              },
              {
                key: 'status',
                title: t('knowledge.field.status'),
                render: (_, row) => <VersionStatusTag status={row.status} />,
              },
              {
                key: 'review_on',
                title: t('knowledge.field.review_on'),
                render: (_, row) =>
                  row.review_on === null ? null : dateFormat.format(new Date(row.review_on)),
              },
            ]}
          />
        </Space>
      </Flex>
      {editing !== undefined && (
        <TopicDialog
          open
          topic={editing.topic}
          parentId={editing.parentId}
          topics={allTopics}
          language={language}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
      <DeleteTopicDialog
        topic={deleting}
        topics={allTopics}
        language={language}
        articleCount={deleting === null ? 0 : articleCount(deleting)}
        onClose={() => {
          setDeleting(null);
        }}
      />
    </Space>
  );
}
