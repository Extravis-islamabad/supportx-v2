import {
  App,
  Button,
  Card,
  Flex,
  Form,
  Input,
  List,
  Popconfirm,
  Radio,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useIncidentCategories,
  useManagedReplyTemplates,
  useReplyTemplateChange,
  useStructure,
  type ReplyTemplate,
  type ReplyTemplateKind,
} from '@supportx/api-client';
import {
  ConflictDialog,
  EmptyText,
  FormProblem,
  markHandled,
  reportError,
  RichTextField,
  RichTextView,
  Tabs,
  useAccess,
  useAppearance,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
  lengthLimit,
} from '@supportx/ui';

import { categoryPath } from '../../incidents/labels';

type Editing = { kind: 'create' } | { kind: 'update'; template: ReplyTemplate } | null;
type Language = 'en' | 'ar' | 'ur';
const LANGUAGES: Language[] = ['en', 'ar', 'ur'];
// The variables a template may use: the type's one catalogue, as notifications have it (041).
const VARIABLES = [
  'record.display_id',
  'record.title',
  'record.priority',
  'record.status',
  'record.link',
  'requester.name',
  'assignee.name',
  'actor.name',
] as const;
const templateView = (template: ReplyTemplate | undefined) =>
  template && { name: template.name, body: template.body };
const blank = (html: string | undefined) => (html ?? '').replace(/<[^>]*>/g, '').trim() === '';

/**
 * Reply templates (REQ-INC-058), managed by admins (settings.manage) here, beside the other
 * incident settings (WP-020c; the composer only inserts them and links here). Open composers
 * reload the list live (`work_items.reply_templates_changed`).
 */
export function ReplyTemplatesTab({ kind = 'reply' }: { kind?: ReplyTemplateKind }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const { can } = useAccess();
  // Shared templates are written with the type's settings right; personal ones by anyone (S5a).
  const mayShare = can('config.service_desk') || can('settings.manage');
  const templates = useManagedReplyTemplates(kind);
  const change = useReplyTemplateChange();
  const groups = useStructure('groups', true, true);
  const categories = useIncidentCategories(kind === 'resolution');
  const [editing, setEditing] = useState<Editing>(null);
  const [name, setName] = useState('');
  const [subject, setSubject] = useState('');
  const [bodies, setBodies] = useState<Partial<Record<Language, string>>>({});
  const [language, setLanguage] = useState<Language>('en');
  const [visibility, setVisibility] = useState<'personal' | 'shared'>('shared');
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [categoryIds, setCategoryIds] = useState<string[]>([]);
  const body = bodies[language] ?? '';
  // Any other refusal (a rule, a limit) is shown in the form too (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const start = (next: Editing) => {
    change.reset();
    problem.clear();
    setChecked(false);
    setEditing(next);
    const template = next?.kind === 'update' ? next.template : undefined;
    setName(template?.name ?? '');
    setSubject(template?.subject ?? '');
    setBodies(template?.bodies ?? {});
    setLanguage('en');
    setVisibility(template?.visibility ?? (mayShare ? 'shared' : 'personal'));
    setGroupIds(template?.group_ids ?? []);
    setCategoryIds(template?.category_ids ?? []);
  };
  const error = change.error instanceof ApiError ? change.error : null;
  // Each problem at its own field (QA6S-SVC-03): a missing one is caught before sending, the
  // server's at the field it names; only what fits no field goes to the form's banner.
  const [checked, setChecked] = useState(false);
  const serverAt = (field: 'name' | 'body') =>
    error?.status === 422
      ? error.fieldErrors
          .filter((f) => f.field === `body.${field}`)
          .map((f) => t(f.message_key, f.params ?? {}))
          .join(' ') || undefined
      : undefined;
  const isEmpty = (field: 'name' | 'body') =>
    field === 'name' ? name.trim() === '' : LANGUAGES.every((lang) => blank(bodies[lang]));
  const problemAt = (field: 'name' | 'body') =>
    checked && isEmpty(field) ? t('errors.field.required') : serverAt(field);
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
      { op: 'delete', id: template.id, version },
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
    setChecked(true);
    if (isEmpty('name') || isEmpty('body')) return;
    const template = {
      kind,
      name,
      subject: kind === 'reply' && subject.trim() !== '' ? subject : null,
      bodies: Object.fromEntries(
        LANGUAGES.filter((lang) => !blank(bodies[lang])).map((lang) => [lang, bodies[lang] ?? '']),
      ),
      visibility,
      group_ids: visibility === 'shared' ? groupIds : [],
      category_ids: kind === 'resolution' ? categoryIds : [],
    };
    change.mutate(
      editing.kind === 'create'
        ? { op: 'create', template }
        : {
            op: 'update',
            id: editing.template.id,
            version: version ?? editing.template.version,
            template,
          },
      {
        onSuccess: () => {
          void message.success(t('reply_templates.saved'));
          start(null);
        },
        onError: (failure) => {
          if (editing.kind === 'update' && stale(editing.template, false)(failure)) return;
          const placed =
            failure instanceof ApiError &&
            failure.status === 422 &&
            failure.fieldErrors.length > 0 &&
            failure.fieldErrors.every(
              (f) => f.field === 'body.name' || f.field.startsWith('body.bodies'),
            );
          if (placed) markHandled(failure);
          else problem.show(failure);
        },
      },
    );
  };
  return (
    <Card
      title={t(kind === 'reply' ? 'reply_templates.title' : 'reply_templates.resolution_title')}
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
      data-testid={kind === 'reply' ? 'settings-reply-templates' : 'settings-resolution-templates'}
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
                actions={
                  template.may_edit
                    ? [
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
                      ]
                    : []
                }
              >
                <List.Item.Meta
                  title={
                    <Space size={8}>
                      <bdi dir="auto">{template.name}</bdi>
                      <Tag>{t(`text_template_visibility.${template.visibility}`)}</Tag>
                    </Space>
                  }
                  description={<RichTextView html={template.body} />}
                />
              </List.Item>
            )}
          />
        </Space>
      ) : (
        <Form layout="vertical" component="div" data-testid="tpl-form">
          <Form.Item
            label={t('reply_templates.name')}
            htmlFor="tpl-name"
            required
            validateStatus={problemAt('name') === undefined ? undefined : 'error'}
            help={problemAt('name')}
          >
            <Input
              id="tpl-name"
              value={name}
              count={lengthLimit(120)}
              onChange={(event) => {
                setName(event.target.value);
              }}
              data-testid="tpl-name"
            />
          </Form.Item>
          {kind === 'reply' && (
            <Form.Item label={t('reply_templates.subject')} htmlFor="tpl-subject">
              <Input
                id="tpl-subject"
                value={subject}
                count={lengthLimit(200)}
                onChange={(event) => {
                  setSubject(event.target.value);
                }}
                data-testid="tpl-subject"
              />
            </Form.Item>
          )}
          <Form.Item
            label={t('reply_templates.body')}
            required
            validateStatus={problemAt('body') === undefined ? undefined : 'error'}
            help={problemAt('body') ?? t('reply_templates.languages_help')}
          >
            <Tabs
              activeKey={language}
              onChange={(key) => {
                setLanguage(key as Language);
              }}
              items={LANGUAGES.map((lang) => ({
                key: lang,
                label: (
                  <span data-testid={`tpl-lang-${lang}`}>
                    {t(`locale.${lang}`)}
                    {blank(bodies[lang]) ? '' : ' •'}
                  </span>
                ),
              }))}
            />
            <RichTextField
              key={language}
              label={`${t('reply_templates.body')} (${t(`locale.${language}`)})`}
              value={body}
              onChange={(html) => {
                setBodies({ ...bodies, [language]: html });
              }}
              testId="tpl-body"
            />
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
              {t('reply_templates.variables_help')}{' '}
              {VARIABLES.map((v) => (
                <Typography.Text key={v} code copyable={{ text: `{{ ${v} }}` }}>
                  {t(`notification_variable.${v}`)}
                </Typography.Text>
              ))}
            </Typography.Paragraph>
          </Form.Item>
          <Form.Item label={t('reply_templates.who')}>
            <Radio.Group
              value={visibility}
              onChange={(event) => {
                setVisibility(event.target.value as 'personal' | 'shared');
              }}
              options={[
                { value: 'personal', label: t('text_template_visibility.personal') },
                {
                  value: 'shared',
                  label: t('text_template_visibility.shared'),
                  disabled: !mayShare,
                },
              ]}
              data-testid="tpl-visibility"
            />
          </Form.Item>
          {visibility === 'shared' && (
            <Form.Item
              label={t('reply_templates.groups')}
              htmlFor="tpl-groups"
              help={t('reply_templates.groups_help')}
            >
              <Select
                id="tpl-groups"
                mode="multiple"
                allowClear
                value={groupIds}
                optionFilterProp="label"
                options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
                onChange={setGroupIds}
                data-testid="tpl-groups"
              />
            </Form.Item>
          )}
          {kind === 'resolution' && (
            <Form.Item
              label={t('reply_templates.categories')}
              htmlFor="tpl-categories"
              help={t('reply_templates.categories_help')}
            >
              <Select
                id="tpl-categories"
                mode="multiple"
                allowClear
                value={categoryIds}
                optionFilterProp="label"
                options={(categories.data ?? [])
                  .filter((c) => !c.disabled)
                  .map((c) => ({
                    value: c.id,
                    label: categoryPath(t, categories.data ?? [], c.id, locale),
                  }))}
                onChange={setCategoryIds}
                data-testid="tpl-categories"
              />
            </Form.Item>
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
        </Form>
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
