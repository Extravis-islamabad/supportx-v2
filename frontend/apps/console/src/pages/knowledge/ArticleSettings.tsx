import { App, DatePicker, Form, Modal, Select, Switch, TreeSelect } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useMemo } from 'react';

import {
  useKbTopics,
  useKbTypes,
  useUpdateKbArticle,
  type KbArticle,
  type KbLanguage,
} from '@supportx/api-client';
import { ConflictDialog, reportError, useConflictRetry, useLabel } from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import type { AudienceValue } from './audience';
import { AudienceFields } from './AudienceFields';
import { showFieldErrors } from './formErrors';
import { topicTree, typeName, type Audience, type TopicNode } from './model';

interface SettingsForm extends AudienceValue {
  topic_id: string;
  type_code: string;
  owner_id: string;
  review_on: Dayjs | null;
  expires_on: Dayjs | null;
  own_audience: boolean;
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

const day = (value: Dayjs | null) => (value === null ? null : value.format('YYYY-MM-DD'));

/**
 * What all versions share (REQ-KB-001, 033, 034, 035, 044): topic, type, owner, review and expiry
 * dates, and the article's own (narrower) audience. If-Match on the article (rule g).
 */
export function ArticleSettings({
  article,
  language,
  onClose,
}: {
  article: KbArticle;
  language: KbLanguage;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const [form] = Form.useForm<SettingsForm>();
  const topics = useKbTopics();
  const types = useKbTypes();
  const update = useUpdateKbArticle(article.id);
  const conflict = useConflictRetry();
  const tree = useMemo(
    () => treeOptions(topicTree(topics.data ?? [], language)),
    [topics.data, language],
  );
  const audience = article.audience as Audience;
  const own = Form.useWatch('own_audience', form) as boolean | undefined;

  const save = (values: SettingsForm, version: number) => {
    const changes = {
      topic_id: values.topic_id,
      type_code: values.type_code,
      owner_id: values.owner_id,
      review_on: day(values.review_on),
      expires_on: day(values.expires_on),
      own_audience: values.own_audience,
      ...(values.own_audience
        ? {
            tech_all: values.tech_all,
            tech_groups: values.tech_all ? [] : values.tech_groups,
            requesters: values.requesters,
            req_groups: values.requesters === 'selected' ? values.req_groups : [],
            req_sites: values.requesters === 'selected' ? values.req_sites : [],
            req_departments: values.requesters === 'selected' ? values.req_departments : [],
          }
        : {}),
    };
    update.mutate(
      { changes, version },
      {
        onSuccess: () => {
          void message.success(t('knowledge.settings_saved'));
          onClose();
        },
        onError: (error) => {
          if (
            conflict.take(error, (latest) => {
              save(values, latest);
            })
          )
            return;
          if (!showFieldErrors(form, error, t)) reportError(error);
        },
      },
    );
  };

  return (
    <Modal
      open
      title={t('knowledge.article_settings')}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      onCancel={onClose}
      onOk={() => {
        form.submit();
      }}
      confirmLoading={update.isPending}
      destroyOnHidden
      width={640}
      data-testid="kb-settings-dialog"
    >
      <ConflictDialog {...conflict.dialog} fieldLabel={(field) => t(`knowledge.field.${field}`)} />
      <Form<SettingsForm>
        form={form}
        layout="vertical"
        initialValues={{
          topic_id: article.topic_id,
          type_code: article.type_code,
          owner_id: article.owner_id,
          review_on: article.review_on === null ? null : dayjs(article.review_on),
          expires_on: article.expires_on === null ? null : dayjs(article.expires_on),
          own_audience: audience.inherited === false,
          tech_all: audience.tech_all ?? true,
          tech_groups: audience.tech_groups ?? [],
          requesters: audience.requesters ?? 'none',
          req_groups: audience.req_groups ?? [],
          req_sites: audience.req_sites ?? [],
          req_departments: audience.req_departments ?? [],
        }}
        onFinish={(values) => {
          save(values, article.version);
        }}
      >
        <Form.Item label={t('knowledge.field.topic_id')} name="topic_id">
          <TreeSelect treeDefaultExpandAll treeData={tree} data-testid="kb-settings-topic" />
        </Form.Item>
        <Form.Item label={t('knowledge.field.type_code')} name="type_code">
          <Select
            options={(types.data ?? [])
              .filter((type) => !type.retired || type.code === article.type_code)
              .map((type) => ({ value: type.code, label: typeName(type, type.code, language, t) }))}
          />
        </Form.Item>
        <Form.Item label={t('knowledge.field.owner_id')} name="owner_id">
          <UserPicker
            value={null}
            onChange={() => undefined}
            current={
              article.owner_name === null || article.owner_name === undefined
                ? null
                : { id: article.owner_id, name: article.owner_name, email: null }
            }
            testId="kb-settings-owner"
            ariaLabel={t('knowledge.field.owner_id')}
          />
        </Form.Item>
        <Form.Item label={t('knowledge.field.review_on')} name="review_on">
          <DatePicker style={{ width: '100%' }} data-testid="kb-settings-review" />
        </Form.Item>
        <Form.Item label={t('knowledge.field.expires_on')} name="expires_on">
          <DatePicker style={{ width: '100%' }} data-testid="kb-settings-expiry" />
        </Form.Item>
        <Form.Item
          label={t('knowledge.field.own_audience')}
          name="own_audience"
          valuePropName="checked"
          extra={t('knowledge.own_audience_help')}
        >
          <Switch data-testid="kb-settings-own-audience" />
        </Form.Item>
        {own === true && <AudienceFields />}
      </Form>
    </Modal>
  );
}
