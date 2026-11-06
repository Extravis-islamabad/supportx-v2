import {
  Alert,
  App,
  Button,
  Card,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';

import {
  useCreateKbType,
  useKbSettings,
  useKbTypes,
  useUpdateKbSettings,
  useUpdateKbType,
  type KbArticleType,
  type KbSettings,
  type KbSettingsPatch,
} from '@supportx/api-client';
import {
  ConflictDialog,
  lengthLimit,
  NoAccess,
  reportError,
  useAccess,
  useAppearance,
  useConflictRetry,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { useKnowledgeLive } from '../../knowledge/live';
import { showFieldErrors } from '../../knowledge/formErrors';
import { articleLanguage, typeName } from '../../knowledge/model';

interface SettingsForm {
  self_approval: boolean;
  requesters_enabled: boolean;
  suggest_on_technician_form: boolean;
  prefix: string;
  next_number: number | null;
}

const formOf = (settings: KbSettings): SettingsForm => ({
  self_approval: settings.self_approval,
  requesters_enabled: settings.requesters_enabled,
  suggest_on_technician_form: settings.suggest_on_technician_form,
  prefix: settings.prefix,
  next_number: settings.next_number,
});

/**
 * Admin › Knowledge (WP-033 3b, D-120; REQ-KB-090): approvals and requesters, article numbering,
 * and article types. Each setting shows its default; saves use If-Match and are audited.
 */
export function KnowledgeSettingsPage() {
  const { can } = useAccess();
  const settingsAllowed = can('knowledge.manage_settings');
  const typesAllowed = can('knowledge.manage_types');
  useKnowledgeLive(settingsAllowed || typesAllowed);
  if (!settingsAllowed && !typesAllowed) return <NoAccess titleKey="knowledge.settings.title" />;
  return (
    <Flex vertical gap={16}>
      {settingsAllowed && <GeneralCard />}
      {typesAllowed && <TypesCard />}
    </Flex>
  );
}

function GeneralCard() {
  const t = useLabel();
  const settings = useKbSettings();
  if (settings.data === undefined) return <Card loading title={t('knowledge.settings.general')} />;
  return <GeneralForm current={settings.data} />;
}

/** The form starts from the settings first shown; a later version only raises the notice. */
function GeneralForm({ current }: { current: KbSettings }) {
  const t = useLabel();
  const { message } = App.useApp();
  const update = useUpdateKbSettings();
  const conflict = useConflictRetry();
  const [form] = Form.useForm<SettingsForm>();
  const [shownVersion, setShownVersion] = useState(current.version);
  // Someone else saved while the form was open: say so, never overwrite their change silently.
  const stale = current.version !== shownVersion;
  const prefix = (Form.useWatch('prefix', form) as string | undefined) ?? current.prefix;
  const next = Form.useWatch('next_number', form) as number | null | undefined;

  const reload = () => {
    form.resetFields();
    form.setFieldsValue(formOf(current));
    setShownVersion(current.version);
  };
  const save = (values: SettingsForm, version: number) => {
    const changes: KbSettingsPatch = {};
    const wanted = { ...values, prefix: values.prefix.trim().toUpperCase() };
    if (wanted.self_approval !== current.self_approval)
      changes.self_approval = wanted.self_approval;
    if (wanted.requesters_enabled !== current.requesters_enabled) {
      changes.requesters_enabled = wanted.requesters_enabled;
    }
    if (wanted.suggest_on_technician_form !== current.suggest_on_technician_form) {
      changes.suggest_on_technician_form = wanted.suggest_on_technician_form;
    }
    if (wanted.prefix !== current.prefix) changes.prefix = wanted.prefix;
    if (wanted.next_number !== null && wanted.next_number !== current.next_number) {
      changes.next_number = wanted.next_number;
    }
    update.mutate(
      { changes, version },
      {
        onSuccess: (saved) => {
          void message.success(t('settings.saved'));
          form.setFieldsValue(formOf(saved));
          setShownVersion(saved.version);
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

  // The server owns the defaults; these match it if an older API leaves them out (D-120 (4)).
  const defaults = current.defaults ?? {
    prefix: 'KB',
    self_approval: false,
    requesters_enabled: true,
    suggest_on_technician_form: true,
  };
  const yesNo = (value: boolean) => t(value ? 'filter.yes' : 'filter.no');
  return (
    <Card title={t('knowledge.settings.general')} data-testid="kb-admin-general">
      <ConflictDialog
        {...conflict.dialog}
        fieldLabel={(field) => t(`knowledge.settings.field.${field}`)}
      />
      {stale && (
        <Alert
          type="warning"
          showIcon
          role="status"
          style={{ marginBottom: 12 }}
          message={t('settings.stale')}
          action={
            <Button size="small" onClick={reload} data-testid="kb-admin-stale-reload">
              {t('live.reload')}
            </Button>
          }
          data-testid="kb-admin-stale"
        />
      )}
      <Form<SettingsForm>
        form={form}
        layout="vertical"
        initialValues={formOf(current)}
        onFinish={(values) => {
          save(values, shownVersion);
        }}
      >
        <Form.Item
          name="self_approval"
          valuePropName="checked"
          label={t('knowledge.settings.field.self_approval')}
          extra={t('knowledge.settings.default_is', { value: yesNo(defaults.self_approval) })}
        >
          <Switch data-testid="kb-admin-self-approval" />
        </Form.Item>
        <Form.Item
          name="requesters_enabled"
          valuePropName="checked"
          label={t('knowledge.settings.field.requesters_enabled')}
          extra={t('knowledge.settings.default_is', {
            value: yesNo(defaults.requesters_enabled),
          })}
        >
          <Switch data-testid="kb-admin-requesters" />
        </Form.Item>
        {/* REQ-KB-062 AC3: off hides the panel on the technician's form; the portal still suggests. */}
        <Form.Item
          name="suggest_on_technician_form"
          valuePropName="checked"
          label={t('knowledge.settings.field.suggest_on_technician_form')}
          extra={t('knowledge.settings.default_is', {
            value: yesNo(defaults.suggest_on_technician_form),
          })}
        >
          <Switch data-testid="kb-admin-suggest" />
        </Form.Item>
        <Typography.Title level={2} style={{ fontSize: 16 }}>
          {t('settings.numbering')}
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          {t('knowledge.settings.numbering_help')}
        </Typography.Paragraph>
        <Flex gap={16} wrap>
          <Form.Item
            name="prefix"
            label={t('settings.prefix')}
            extra={t('knowledge.settings.default_is', { value: defaults.prefix })}
            normalize={(value: string) => value.toUpperCase()}
          >
            <Input
              dir="ltr"
              count={lengthLimit(6)}
              style={{ width: 140 }}
              data-testid="kb-admin-prefix"
            />
          </Form.Item>
          <Form.Item
            name="next_number"
            label={t('settings.next_number')}
            extra={t('settings.next_number_help', { minimum: current.next_number })}
          >
            <InputNumber min={1} precision={0} style={{ width: 160 }} data-testid="kb-admin-next" />
          </Form.Item>
        </Flex>
        <Typography.Paragraph data-testid="kb-admin-next-id">
          {t('knowledge.settings.next_id', {
            id: `${prefix.trim().toUpperCase()}-${String(next ?? current.next_number)}`,
          })}
        </Typography.Paragraph>
        <Space wrap>
          <WriteButton
            type="primary"
            htmlType="submit"
            loading={update.isPending}
            data-testid="kb-admin-save"
          >
            {t('actions.save')}
          </WriteButton>
          <Button onClick={reload}>{t('actions.reset')}</Button>
          <Button
            onClick={() => {
              form.setFieldsValue({
                self_approval: defaults.self_approval,
                requesters_enabled: defaults.requesters_enabled,
                suggest_on_technician_form: defaults.suggest_on_technician_form,
                prefix: defaults.prefix,
              });
            }}
            data-testid="kb-admin-defaults"
          >
            {t('knowledge.settings.use_defaults')}
          </Button>
        </Space>
      </Form>
    </Card>
  );
}

interface TypeForm {
  name_en: string;
  name_ar: string;
  name_ur: string;
  review_months: number | null;
}

const TYPE_NAMES = { 'names.en': 'name_en', 'names.ar': 'name_ar', 'names.ur': 'name_ur' };

function TypesCard() {
  const t = useLabel();
  const { locale } = useAppearance();
  const language = articleLanguage(locale);
  const { message, modal } = App.useApp();
  const types = useKbTypes();
  const update = useUpdateKbType();
  const conflict = useConflictRetry();
  const [editing, setEditing] = useState<KbArticleType | 'new' | null>(null);

  const retire = (kind: KbArticleType, retired: boolean, version: number) => {
    update.mutate(
      { code: kind.code, changes: { retired }, version },
      {
        onSuccess: () => {
          void message.success(
            t(retired ? 'knowledge.types.retired_done' : 'knowledge.types.restored_done'),
          );
        },
        onError: (error) => {
          if (
            !conflict.take(error, (latest) => {
              retire(kind, retired, latest);
            })
          )
            reportError(error);
        },
      },
    );
  };

  return (
    <Card
      title={t('knowledge.types.title')}
      extra={
        <WriteButton
          onClick={() => {
            setEditing('new');
          }}
          data-testid="kb-admin-type-add"
        >
          {t('knowledge.types.add')}
        </WriteButton>
      }
      data-testid="kb-admin-types"
    >
      <ConflictDialog
        {...conflict.dialog}
        fieldLabel={(field) => t(`knowledge.types.field.${field}`)}
      />
      <Typography.Paragraph type="secondary">{t('knowledge.types.help')}</Typography.Paragraph>
      <Table<KbArticleType>
        rowKey="code"
        loading={types.isPending}
        dataSource={types.data ?? []}
        pagination={false}
        scroll={{ x: true }}
        columns={[
          {
            key: 'name',
            title: t('knowledge.types.field.name'),
            render: (_, kind) => (
              <Space wrap>
                <span dir="auto">{typeName(kind, kind.code, language, t)}</span>
                {kind.builtin && <Tag>{t('knowledge.types.builtin')}</Tag>}
                {kind.retired && <Tag color="default">{t('knowledge.types.retired')}</Tag>}
              </Space>
            ),
          },
          {
            key: 'review',
            title: t('knowledge.types.field.review_months'),
            render: (_, kind) => t('knowledge.types.months', { count: kind.review_months }),
          },
          {
            key: 'actions',
            title: t('knowledge.types.actions'),
            render: (_, kind) => (
              <Space wrap>
                <Button
                  size="small"
                  onClick={() => {
                    setEditing(kind);
                  }}
                  data-testid={`kb-admin-type-edit-${kind.code}`}
                >
                  {t('actions.edit')}
                </Button>
                <WriteButton
                  size="small"
                  onClick={() => {
                    if (kind.retired) {
                      retire(kind, false, kind.version); // restoring loses nothing
                      return;
                    }
                    // Retiring changes what authors may pick: it asks first, naming the type and
                    // what happens (QA6S-SVC-18: it applied at once).
                    const name = typeName(kind, kind.code, language, t);
                    modal.confirm({
                      title: t('knowledge.types.retire_confirm', { name }),
                      content: t('knowledge.types.retire_explain'),
                      okText: t('knowledge.types.retire'),
                      okButtonProps: {
                        danger: true,
                        'data-testid': 'kb-admin-type-retire-ok',
                      },
                      cancelText: t('actions.cancel'),
                      onOk: () => {
                        retire(kind, true, kind.version);
                      },
                    });
                  }}
                  data-testid={`kb-admin-type-retire-${kind.code}`}
                >
                  {t(kind.retired ? 'knowledge.types.restore' : 'knowledge.types.retire')}
                </WriteButton>
              </Space>
            ),
          },
        ]}
      />
      {editing !== null && (
        <TypeDialog
          kind={editing === 'new' ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </Card>
  );
}

/** Add a custom type, or change one: a built-in type keeps its names (they are labels). */
function TypeDialog({ kind, onClose }: { kind: KbArticleType | null; onClose: () => void }) {
  const t = useLabel();
  const { message } = App.useApp();
  const [form] = Form.useForm<TypeForm>();
  const create = useCreateKbType();
  const update = useUpdateKbType();
  const conflict = useConflictRetry();
  const [key] = useState(() => crypto.randomUUID());
  const builtin = kind?.builtin ?? false;

  const done = () => {
    void message.success(t('knowledge.types.saved'));
    onClose();
  };
  const failed = (error: unknown, again: (latest: number) => void) => {
    if (conflict.take(error, again)) return;
    if (!showFieldErrors(form, error, t, TYPE_NAMES)) reportError(error);
  };
  const save = (values: TypeForm, version: number) => {
    const names = { en: values.name_en, ar: values.name_ar, ur: values.name_ur };
    const months = values.review_months ?? 12;
    if (kind === null) {
      create.mutate(
        { body: { names, review_months: months }, key },
        {
          onSuccess: done,
          onError: (error) => {
            failed(error, () => undefined);
          },
        },
      );
      return;
    }
    update.mutate(
      {
        code: kind.code,
        changes: builtin ? { review_months: months } : { names, review_months: months },
        version,
      },
      {
        onSuccess: done,
        onError: (error) => {
          failed(error, (latest) => {
            save(values, latest);
          });
        },
      },
    );
  };

  return (
    <Modal
      open
      title={t(kind === null ? 'knowledge.types.add' : 'knowledge.types.edit')}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      onCancel={onClose}
      onOk={() => {
        form.submit();
      }}
      confirmLoading={create.isPending || update.isPending}
      destroyOnHidden
      data-testid="kb-admin-type-dialog"
    >
      <ConflictDialog
        {...conflict.dialog}
        fieldLabel={(field) => t(`knowledge.types.field.${field}`)}
      />
      <Form<TypeForm>
        form={form}
        layout="vertical"
        initialValues={{
          name_en: kind?.names.en ?? '',
          name_ar: kind?.names.ar ?? '',
          name_ur: kind?.names.ur ?? '',
          review_months: kind?.review_months ?? 12,
        }}
        onFinish={(values) => {
          save(values, kind?.version ?? 0);
        }}
      >
        {builtin ? (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={t('knowledge.types.builtin_names')}
          />
        ) : (
          <>
            <Form.Item
              name="name_en"
              label={t('knowledge.types.field.name_en')}
              rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
            >
              <Input count={lengthLimit(60)} dir="ltr" lang="en" data-testid="kb-admin-type-en" />
            </Form.Item>
            <Form.Item
              name="name_ar"
              label={t('knowledge.types.field.name_ar')}
              rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
            >
              <Input count={lengthLimit(60)} dir="rtl" lang="ar" data-testid="kb-admin-type-ar" />
            </Form.Item>
            <Form.Item name="name_ur" label={t('knowledge.types.field.name_ur')}>
              <Input count={lengthLimit(60)} dir="rtl" lang="ur" data-testid="kb-admin-type-ur" />
            </Form.Item>
          </>
        )}
        <Form.Item
          name="review_months"
          label={t('knowledge.types.field.review_months')}
          rules={[{ required: true, message: t('errors.field.required') }]}
        >
          <InputNumber min={1} max={60} precision={0} data-testid="kb-admin-type-months" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
