import { Alert, App, Button, Card, Flex, Input, List, Popconfirm, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useReplyTemplateChange,
  useReplyTemplates,
  type ReplyTemplate,
} from '@supportx/api-client';
import {
  ConflictDialog,
  describeError,
  EmptyText,
  FormProblem,
  markHandled,
  reportError,
  RichTextField,
  RichTextView,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
  lengthLimit,
} from '@supportx/ui';

type Editing = { kind: 'create' } | { kind: 'update'; template: ReplyTemplate } | null;
const templateView = (template: ReplyTemplate | undefined) =>
  template && { name: template.name, body: template.body };

/**
 * Reply templates (REQ-INC-058), managed by admins (settings.manage) here, beside the other
 * incident settings (WP-020c; the composer only inserts them and links here). Open composers
 * reload the list live (`work_items.reply_templates_changed`).
 */
export function ReplyTemplatesTab() {
  const t = useLabel();
  const { message } = App.useApp();
  const templates = useReplyTemplates();
  const change = useReplyTemplateChange();
  const [editing, setEditing] = useState<Editing>(null);
  const [name, setName] = useState('');
  const [body, setBody] = useState('');
  // Any other refusal (a rule, a limit) is shown in the form too (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const start = (next: Editing) => {
    change.reset();
    problem.clear();
    setEditing(next);
    setName(next?.kind === 'update' ? next.template.name : '');
    setBody(next?.kind === 'update' ? next.template.body : '');
  };
  const error = change.error instanceof ApiError ? change.error : null;
  // A template someone changed first (409): the shared dialog (QA WP-029 BUG-05).
  const conflict = useConflict();
  const [tried, setTried] = useState<{ template: ReplyTemplate; remove: boolean }>();
  const live = templates.data?.find((x) => x.id === tried?.template.id);
  const stale = (template: ReplyTemplate, remove: boolean) => (failure: unknown) => {
    if (!conflict.take(failure)) return false;
    setTried({ template, remove });
    void templates.refetch();
    return true;
  };
  const remove = (template: ReplyTemplate, version = template.version) => {
    change.mutate(
      { kind: 'delete', id: template.id, version },
      {
        onError: (failure) => {
          if (!stale(template, true)(failure)) reportError(failure);
        },
      },
    );
  };
  const save = (version?: number) => {
    if (editing === null) return;
    problem.clear();
    change.mutate(
      editing.kind === 'create'
        ? { kind: 'create', name, body }
        : {
            kind: 'update',
            id: editing.template.id,
            version: version ?? editing.template.version,
            name,
            body,
          },
      {
        onSuccess: () => {
          void message.success(t('reply_templates.saved'));
          start(null);
        },
        onError: (failure) => {
          if (editing.kind === 'update' && stale(editing.template, false)(failure)) return;
          if (failure instanceof ApiError && failure.status === 422) markHandled(failure);
          else problem.show(failure);
        },
      },
    );
  };
  return (
    <Card
      title={t('reply_templates.title')}
      // In the header like every other settings card (QA C7).
      extra={
        editing === null ? (
          <WriteButton
            type="primary"
            onClick={() => {
              start({ kind: 'create' });
            }}
            data-testid="tpl-new"
          >
            {t('reply_templates.new')}
          </WriteButton>
        ) : null
      }
      data-testid="settings-reply-templates"
    >
      {editing === null ? (
        <Space direction="vertical" style={{ width: '100%' }}>
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
                    description={t('reply_templates.remove_explained')}
                    okText={t('reply_templates.remove')}
                    okButtonProps={{ danger: true }}
                    cancelText={t('actions.cancel')}
                    onConfirm={() => {
                      remove(template);
                    }}
                  >
                    <Button type="link" danger>
                      {t('reply_templates.remove')}
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
            count={lengthLimit(120)}
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
          <FormProblem problem={problem} />
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
              onClick={() => {
                save();
              }}
              data-testid="tpl-save"
            >
              {t('actions.save')}
            </WriteButton>
          </Flex>
        </Space>
      )}
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) =>
          t(field === 'body' ? 'reply_templates.body' : 'reply_templates.name')
        }
        opened={templateView(tried?.template)}
        latest={templateView(live)}
        onReload={() => {
          conflict.clear();
          // An open form shows their version, my edits dropped.
          if (!tried?.remove && live !== undefined) start({ kind: 'update', template: live });
          setTried(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined && live !== undefined) {
            const version = conflict.latestVersion ?? live.version;
            if (tried.remove) remove(live, version);
            else {
              setEditing({ kind: 'update', template: live });
              save(version);
            }
          }
          setTried(undefined);
        }}
      />
    </Card>
  );
}
