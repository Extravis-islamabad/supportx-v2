import { Alert, App, Button, Flex, Input, List, Modal, Popconfirm, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useReplyTemplateChange,
  useReplyTemplates,
  type ReplyTemplate,
} from '@supportx/api-client';
import {
  describeError,
  EmptyText,
  reportError,
  RichTextField,
  RichTextView,
  useLabel,
  WriteButton,
} from '@supportx/ui';

type Editing = { kind: 'create' } | { kind: 'update'; template: ReplyTemplate } | null;

/**
 * Reply templates (REQ-INC-058), managed by admins (settings.manage) from the composer. The
 * incident settings screens (WP-020c) will list this beside the other incident settings.
 */
export function ReplyTemplatesDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  const templates = useReplyTemplates(open);
  const change = useReplyTemplateChange();
  const [editing, setEditing] = useState<Editing>(null);
  const [name, setName] = useState('');
  const [body, setBody] = useState('');
  const start = (next: Editing) => {
    change.reset();
    setEditing(next);
    setName(next?.kind === 'update' ? next.template.name : '');
    setBody(next?.kind === 'update' ? next.template.body : '');
  };
  const error = change.error instanceof ApiError ? change.error : null;
  const save = () => {
    if (editing === null) return;
    change.mutate(
      editing.kind === 'create'
        ? { kind: 'create', name, body }
        : {
            kind: 'update',
            id: editing.template.id,
            version: editing.template.version,
            name,
            body,
          },
      {
        onSuccess: () => {
          void message.success(t('reply_templates.saved'));
          start(null);
        },
        onError: (failure) => {
          if (!(failure instanceof ApiError && failure.status === 422)) reportError(failure);
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      title={t('reply_templates.title')}
      onCancel={() => {
        start(null);
        onClose();
      }}
      footer={null}
      width={760}
      destroyOnHidden
    >
      {editing === null ? (
        <Space direction="vertical" style={{ width: '100%' }}>
          <Flex justify="end">
            <WriteButton
              type="primary"
              onClick={() => {
                start({ kind: 'create' });
              }}
              data-testid="tpl-new"
            >
              {t('reply_templates.new')}
            </WriteButton>
          </Flex>
          <List
            loading={templates.isPending}
            dataSource={templates.data ?? []}
            locale={{ emptyText: <EmptyText>{t('reply_templates.none')}</EmptyText> }}
            data-testid="tpl-list"
            renderItem={(template) => (
              <List.Item
                actions={[
                  <Button
                    key="edit"
                    type="link"
                    onClick={() => {
                      start({ kind: 'update', template });
                    }}
                  >
                    {t('actions.edit')}
                  </Button>,
                  <Popconfirm
                    key="delete"
                    title={t('reply_templates.delete_confirm', { name: template.name })}
                    okText={t('actions.delete')}
                    okButtonProps={{ danger: true }}
                    cancelText={t('actions.cancel')}
                    onConfirm={() => {
                      change.mutate(
                        { kind: 'delete', id: template.id, version: template.version },
                        { onError: reportError },
                      );
                    }}
                  >
                    <Button type="link" danger>
                      {t('actions.delete')}
                    </Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  title={<bdi dir="auto">{template.name}</bdi>}
                  description={<RichTextView html={template.body} />}
                />
              </List.Item>
            )}
          />
        </Space>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} data-testid="tpl-form">
          <label htmlFor="tpl-name">{t('reply_templates.name')}</label>
          <Input
            id="tpl-name"
            value={name}
            maxLength={120}
            onChange={(event) => {
              setName(event.target.value);
            }}
            data-testid="tpl-name"
          />
          <Typography.Text>{t('reply_templates.body')}</Typography.Text>
          <RichTextField
            label={t('reply_templates.body')}
            value={body}
            onChange={setBody}
            testId="tpl-body"
          />
          {error?.status === 422 && (
            <Alert
              type="error"
              showIcon
              message={describeError(error, t).title}
              description={error.fieldErrors.map((f) => t(f.message_key, f.params ?? {})).join(' ')}
            />
          )}
          <Flex justify="end" gap={8}>
            <Button
              onClick={() => {
                start(null);
              }}
            >
              {t('actions.cancel')}
            </Button>
            <WriteButton
              type="primary"
              loading={change.isPending}
              onClick={save}
              data-testid="tpl-save"
            >
              {t('actions.save')}
            </WriteButton>
          </Flex>
        </Space>
      )}
    </Modal>
  );
}
