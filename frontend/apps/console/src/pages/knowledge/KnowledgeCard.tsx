import {
  App,
  Alert,
  Button,
  Card,
  Form,
  List,
  Modal,
  Select,
  Skeleton,
  Space,
  Tag,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  queryKeys,
  useKbFromRecord,
  useKbRecordArticles,
  useKbTopics,
  useKbTypes,
  useLinkKbArticle,
  useUnlinkKbArticle,
  type KbFromRecord,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import { reportError, useAccess, useAppearance, useLabel, WriteButton } from '@supportx/ui';
import { useQueryClient } from '@tanstack/react-query';

import { KnowledgePicker } from './KnowledgePicker';
import { articleLanguage, topicTree, typeName, type TopicNode } from './model';

const LAST_TOPIC = (userId: string) => `sx.kb.lastTopic.${userId}`;

/** The topic this author used last for "save as knowledge" (a convenience; storage may fail). */
function lastTopic(userId: string): string | undefined {
  try {
    return localStorage.getItem(LAST_TOPIC(userId)) ?? undefined;
  } catch {
    return undefined;
  }
}
function rememberTopic(userId: string, topicId: string): void {
  try {
    localStorage.setItem(LAST_TOPIC(userId), topicId);
  } catch {
    // private mode or blocked storage: the next dialog simply starts empty
  }
}

interface TreeOption {
  value: string;
  title: string;
  children: TreeOption[];
}
const treeOptions = (nodes: TopicNode[]): TreeOption[] =>
  nodes.map((node) => ({
    value: node.key,
    title: node.title,
    children: treeOptions(node.children),
  }));

/**
 * The record's knowledge (D-121; lane A's choice: a card in the side panel): the linked articles
 * the reader may read, "N restricted" for the others, linking an article, and saving the
 * resolution as knowledge. Live on the record's channel.
 */
export function KnowledgeCard({
  recordType,
  recordId,
  subject,
  hasResolution,
  userId,
}: {
  recordType: string;
  recordId: string;
  subject: string;
  hasResolution: boolean;
  userId: string;
}) {
  const t = useLabel();
  const { can } = useAccess();
  const { locale } = useAppearance();
  const language = articleLanguage(locale);
  const queryClient = useQueryClient();
  const allowed = can('knowledge.view');
  const found = useKbRecordArticles(recordType, recordId, allowed);
  const linkIt = useLinkKbArticle();
  const unlink = useUnlinkKbArticle();
  const [saving, setSaving] = useState(false);
  useRecordChannel(allowed ? 'wi' : 'none', allowed ? recordId : undefined, (message) => {
    if (message.type === 'knowledge.link.saved' || message.type === 'knowledge.link.removed') {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledge.recordArticles(recordType, recordId),
      });
    }
  });
  if (!allowed) return null;
  const items = found.data?.items ?? [];
  const restricted = found.data?.restricted ?? 0;

  return (
    <Card
      title={t('knowledge.card.title')}
      size="small"
      data-testid="kb-card"
      extra={
        <Space size={4} wrap>
          <KnowledgePicker
            recordType={recordType}
            recordId={recordId}
            subject={subject}
            audience="private"
            buttonLabel={t('knowledge.card.link')}
            onPick={async (row) => {
              await linkIt.mutateAsync({
                articleId: row.id,
                recordType,
                recordId,
                key: crypto.randomUUID(),
              });
            }}
          />
          {can('knowledge.create') && hasResolution && (
            <WriteButton
              size="small"
              onClick={() => {
                setSaving(true);
              }}
              data-testid="kb-card-save"
            >
              {t('knowledge.card.save_as')}
            </WriteButton>
          )}
        </Space>
      }
    >
      <List
        size="small"
        loading={found.isPending}
        dataSource={items}
        // AntD greys an empty list's text to the disabled colour, which fails AA contrast on
        // the record panel (axe, D-124): secondary text keeps it readable.
        locale={{
          emptyText: (
            <Typography.Text type="secondary">{t('knowledge.card.empty')}</Typography.Text>
          ),
        }}
        renderItem={(item) => {
          const shown =
            item.article.published[language] ??
            Object.values(item.article.published)[0] ??
            Object.values(item.article.drafts)[0];
          return (
            <List.Item
              key={item.link_id}
              data-testid={`kb-card-item-${item.article.display_id}`}
              actions={
                item.article.can_edit
                  ? [
                      <Button
                        key="unlink"
                        size="small"
                        type="link"
                        onClick={() => {
                          unlink.mutate(
                            {
                              articleId: item.article.id,
                              linkId: item.link_id,
                              recordType,
                              recordId,
                            },
                            { onError: reportError },
                          );
                        }}
                        data-testid={`kb-card-unlink-${item.article.display_id}`}
                      >
                        {t('knowledge.card.unlink')}
                      </Button>,
                    ]
                  : []
              }
            >
              <Space direction="vertical" size={0} style={{ minWidth: 0 }}>
                <Link to={`/knowledge/articles/${item.article.id}`}>
                  <span dir="auto">{shown?.title ?? item.article.display_id}</span>
                </Link>
                <Space size={4}>
                  <Typography.Text type="secondary">{item.article.display_id}</Typography.Text>
                  <Tag>{t(`kb_link_source.${item.source}`)}</Tag>
                </Space>
              </Space>
            </List.Item>
          );
        }}
      />
      {restricted > 0 && (
        <Typography.Text type="secondary" data-testid="kb-card-restricted">
          {t('knowledge.card.restricted', { count: restricted })}
        </Typography.Text>
      )}
      {saving && (
        <SaveAsKnowledge
          recordType={recordType}
          recordId={recordId}
          userId={userId}
          onClose={() => {
            setSaving(false);
          }}
        />
      )}
    </Card>
  );
}

/** "Save as knowledge" (REQ-KB-016): topic (the last one used pre-selected), type; a new draft. */
function SaveAsKnowledge({
  recordType,
  recordId,
  userId,
  onClose,
}: {
  recordType: string;
  recordId: string;
  userId: string;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const language = articleLanguage(locale);
  const { message } = App.useApp();
  const navigate = useNavigate();
  const topics = useKbTopics();
  const types = useKbTypes();
  const make = useKbFromRecord();
  const [key] = useState(() => crypto.randomUUID());
  const [made, setMade] = useState<KbFromRecord>();
  const [form] = Form.useForm<{ topic_id: string; type_code: string }>();
  const tree = useMemo(
    () => treeOptions(topicTree(topics.data ?? [], language)),
    [topics.data, language],
  );
  const remembered = lastTopic(userId);
  const known = (topics.data ?? []).some((topic) => topic.id === remembered);

  const open = (result: KbFromRecord) => {
    const draftLanguage = Object.keys(result.article.drafts)[0] ?? 'en';
    void navigate(`/knowledge/articles/${result.article.id}/edit/${draftLanguage}`);
  };

  if (made !== undefined) {
    return (
      <Modal
        open
        title={t('knowledge.card.personal_title')}
        okText={t('knowledge.card.open_draft')}
        cancelText={t('actions.close')}
        onOk={() => {
          open(made);
        }}
        onCancel={onClose}
        data-testid="kb-save-personal"
      >
        <Alert
          type="warning"
          showIcon
          message={t('knowledge.card.personal_text')}
          description={
            <ul style={{ margin: 0, paddingInlineStart: 20 }}>
              {made.personal_data.map((finding) => (
                <li key={`${finding.field}-${finding.kind}`}>
                  {t('knowledge.card.personal_item', {
                    kind: t(`kb_personal_data.${finding.kind}`),
                    field: t(`kb_personal_field.${finding.field}`),
                  })}
                </li>
              ))}
            </ul>
          }
        />
      </Modal>
    );
  }

  return (
    <Modal
      open
      title={t('knowledge.card.save_as')}
      okText={t('knowledge.card.save_ok')}
      cancelText={t('actions.cancel')}
      confirmLoading={make.isPending}
      onCancel={onClose}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
      data-testid="kb-save-dialog"
    >
      <Typography.Paragraph type="secondary">{t('knowledge.card.save_help')}</Typography.Paragraph>
      {/* The topics first: the last one used can only be pre-selected once they are known. */}
      {topics.data === undefined ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : (
        <Form
          form={form}
          layout="vertical"
          initialValues={{ topic_id: known ? remembered : undefined, type_code: 'how_to' }}
          onFinish={(values) => {
            rememberTopic(userId, values.topic_id);
            make.mutate(
              { recordType, recordId, topicId: values.topic_id, typeCode: values.type_code, key },
              {
                onSuccess: (result) => {
                  void message.success(t('knowledge.card.saved'));
                  if (result.personal_data.length > 0) setMade(result);
                  else open(result);
                },
                onError: reportError,
              },
            );
          }}
        >
          <Form.Item
            name="topic_id"
            label={t('knowledge.field.topic')}
            rules={[{ required: true, message: t('errors.field.required') }]}
          >
            <TreeSelect
              treeData={tree}
              treeDefaultExpandAll
              showSearch
              data-testid="kb-save-topic"
            />
          </Form.Item>
          <Form.Item name="type_code" label={t('knowledge.field.type')}>
            <Select
              data-testid="kb-save-type"
              options={(types.data ?? [])
                .filter((kind) => !kind.retired)
                .map((kind) => ({
                  value: kind.code,
                  label: typeName(kind, kind.code, language, t),
                }))}
            />
          </Form.Item>
        </Form>
      )}
    </Modal>
  );
}
