import { App, Form, Input, Modal, TreeSelect, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  useCreateKbTopic,
  useDeleteKbTopic,
  useUpdateKbTopic,
  type KbLanguage,
  type KbTopic,
} from '@supportx/api-client';
import { ConflictDialog, lengthLimit, reportError, useConflictRetry, useLabel } from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import { EVERYONE_STAFF, type AudienceValue } from './audience';
import { AudienceFields } from './AudienceFields';
import { showFieldErrors } from './formErrors';
import { subtreeIds, topicTree, type TopicNode } from './model';

interface TopicForm extends AudienceValue {
  name_en: string;
  name_ar?: string;
  parent_id?: string | null;
  owner_id?: string | null;
}

interface TreeOption {
  value: string;
  title: string;
  disabled?: boolean;
  children: TreeOption[];
}

function treeOptions(nodes: TopicNode[], blocked: Set<string>): TreeOption[] {
  return nodes.map((node) => ({
    value: node.key,
    title: node.title,
    disabled: blocked.has(node.key),
    children: treeOptions(node.children, blocked),
  }));
}

/** New topic, or change one (names, place, owner, audience); If-Match on save (rule g). */
export function TopicDialog({
  open,
  topic,
  parentId,
  topics,
  language,
  onClose,
}: {
  open: boolean;
  topic: KbTopic | null;
  parentId: string | null;
  topics: readonly KbTopic[];
  language: KbLanguage;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const [form] = Form.useForm<TopicForm>();
  const create = useCreateKbTopic();
  const update = useUpdateKbTopic();
  const conflict = useConflictRetry();
  const [key] = useState(() => crypto.randomUUID());
  // A topic never goes under itself or its own subtopics.
  const blocked = useMemo(
    () => (topic === null ? new Set<string>() : subtreeIds(topics, topic.id)),
    [topic, topics],
  );
  const names = (topic?.names ?? {}) as Record<string, string | undefined>;
  const initial: TopicForm =
    topic === null
      ? { ...EVERYONE_STAFF, name_en: '', parent_id: parentId }
      : {
          name_en: names.en ?? '',
          name_ar: names.ar,
          parent_id: topic.parent_id,
          owner_id: topic.owner_id,
          tech_all: topic.tech_all,
          tech_groups: topic.tech_groups,
          requesters: topic.requesters as AudienceValue['requesters'],
          req_groups: topic.req_groups,
          req_sites: topic.req_sites,
          req_departments: topic.req_departments,
        };

  const save = (values: TopicForm, version?: number) => {
    const body = {
      names: {
        en: values.name_en,
        ...(values.name_ar?.trim() ? { ar: values.name_ar } : {}),
      },
      parent_id: values.parent_id ?? null,
      owner_id: values.owner_id ?? null,
      tech_all: values.tech_all,
      tech_groups: values.tech_all ? [] : values.tech_groups,
      requesters: values.requesters,
      req_groups: values.requesters === 'selected' ? values.req_groups : [],
      req_sites: values.requesters === 'selected' ? values.req_sites : [],
      req_departments: values.requesters === 'selected' ? values.req_departments : [],
    };
    const done = () => {
      void message.success(t('knowledge.topic_saved'));
      onClose();
    };
    const failed = (error: unknown) => {
      if (
        topic !== null &&
        conflict.take(error, (latest) => {
          save(values, latest);
        })
      )
        return;
      if (!showFieldErrors(form, error, t, { 'names.en': 'name_en', names: 'name_en' }))
        reportError(error);
    };
    if (topic === null) create.mutate({ body, key }, { onSuccess: done, onError: failed });
    else
      update.mutate(
        { id: topic.id, changes: body, version: version ?? topic.version },
        { onSuccess: done, onError: failed },
      );
  };

  return (
    <Modal
      open={open}
      title={t(topic === null ? 'knowledge.new_topic' : 'knowledge.edit_topic')}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      onCancel={onClose}
      onOk={() => {
        form.submit();
      }}
      confirmLoading={create.isPending || update.isPending}
      destroyOnHidden
      data-testid="kb-topic-dialog"
    >
      <ConflictDialog {...conflict.dialog} fieldLabel={(field) => t(`knowledge.field.${field}`)} />
      <Form<TopicForm>
        form={form}
        layout="vertical"
        initialValues={initial}
        onFinish={(values) => {
          save(values);
        }}
      >
        <Form.Item
          label={t('knowledge.field.name_en')}
          name="name_en"
          rules={[{ required: true, whitespace: true, message: t('errors.field.name_required') }]}
        >
          <Input count={lengthLimit(200)} data-testid="kb-topic-name-en" />
        </Form.Item>
        <Form.Item label={t('knowledge.field.name_ar')} name="name_ar">
          <Input count={lengthLimit(200)} dir="rtl" data-testid="kb-topic-name-ar" />
        </Form.Item>
        <Form.Item label={t('knowledge.field.parent_id')} name="parent_id">
          <TreeSelect
            allowClear
            treeDefaultExpandAll
            placeholder={t('knowledge.top_level')}
            treeData={treeOptions(topicTree(topics, language), blocked)}
            data-testid="kb-topic-parent"
          />
        </Form.Item>
        <Form.Item label={t('knowledge.field.owner_id')} name="owner_id">
          <UserPicker
            value={null}
            onChange={() => undefined}
            testId="kb-topic-owner"
            ariaLabel={t('knowledge.field.owner_id')}
          />
        </Form.Item>
        <AudienceFields />
      </Form>
    </Modal>
  );
}

/** Delete a topic: its articles must move somewhere first ("move its N articles to…"). */
export function DeleteTopicDialog({
  topic,
  topics,
  language,
  articleCount,
  onClose,
}: {
  topic: KbTopic | null;
  topics: readonly KbTopic[];
  language: KbLanguage;
  articleCount: number;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const remove = useDeleteKbTopic();
  const conflict = useConflictRetry();
  const [target, setTarget] = useState<string | undefined>();
  const blocked = useMemo(
    () => (topic === null ? new Set<string>() : subtreeIds(topics, topic.id)),
    [topic, topics],
  );
  if (topic === null) return null;
  const go = (version: number) => {
    remove.mutate(
      { id: topic.id, version, moveTo: target },
      {
        onSuccess: () => {
          void message.success(t('knowledge.topic_deleted'));
          onClose();
        },
        onError: (error) => {
          if (!conflict.take(error, go)) reportError(error);
        },
      },
    );
  };
  return (
    <Modal
      open
      title={t('knowledge.delete_topic')}
      okText={t('actions.delete')}
      okButtonProps={{ danger: true, disabled: articleCount > 0 && target === undefined }}
      cancelText={t('actions.cancel')}
      onCancel={onClose}
      onOk={() => {
        go(topic.version);
      }}
      confirmLoading={remove.isPending}
      destroyOnHidden
      data-testid="kb-topic-delete"
    >
      <ConflictDialog {...conflict.dialog} fieldLabel={(field) => t(`knowledge.field.${field}`)} />
      <Typography.Paragraph>{t('knowledge.delete_topic_explain')}</Typography.Paragraph>
      {articleCount > 0 && (
        <>
          <label htmlFor="kb-move-to">
            {t('knowledge.move_articles_to', { n: String(articleCount) })}
          </label>
          <TreeSelect
            id="kb-move-to"
            style={{ width: '100%' }}
            treeDefaultExpandAll
            value={target}
            onChange={setTarget}
            treeData={treeOptions(topicTree(topics, language), blocked)}
            data-testid="kb-move-to"
          />
        </>
      )}
    </Modal>
  );
}
