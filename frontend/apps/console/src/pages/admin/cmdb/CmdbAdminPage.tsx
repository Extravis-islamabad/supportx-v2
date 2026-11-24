import { useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link } from 'react-router';

import {
  queryKeys,
  useCiStates,
  useCiTypes,
  useCmdbSettings,
  useCreateCiState,
  useCreateCiType,
  useDeleteCiState,
  useDeleteCiType,
  useUpdateCiType,
  useUpdateCmdbSettings,
  type CiState,
  type CiType,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  NoAccess,
  SettingsCard,
  SettingsPageHeader,
  WriteButton,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { nameOf, typeTree } from '../../cmdb/names';
import { ciTypeFieldsHref } from './links';
import { TriggersTab } from '../automation/TriggersTab';
import { RelationshipTypesBlock } from './RelationshipTypesBlock';
import { SourceOrderBlock } from './SourceOrderBlock';

interface TypeDraft {
  api_name: string;
  name_en: string;
  name_ar?: string;
  name_ur?: string;
  parent_id?: string;
}

function names(draft: Pick<TypeDraft, 'name_en' | 'name_ar' | 'name_ur'>): Record<string, string> {
  const out: Record<string, string> = { en: draft.name_en.trim() };
  if (draft.name_ar?.trim()) out.ar = draft.name_ar.trim();
  if (draft.name_ur?.trim()) out.ur = draft.name_ur.trim();
  return out;
}

/**
 * CMDB setup (template E, D-147): the settings, the CI type tree and the CI states. Each type's
 * custom fields (metadata's, 0175) are on its own Fields page. Every change is audited and
 * reaches open screens live.
 */
export function CmdbAdminPage() {
  const t = useLabel();
  const { can } = useAccess();
  const allowed = can('cmdb.configure');
  const queryClient = useQueryClient();
  useTenantChannel((message) => {
    if (
      message.type === 'cmdb.config_changed' ||
      message.type === 'cmdb.sync_changed' ||
      message.type === 'refresh'
    ) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.all });
    }
  });
  if (!allowed) return <NoAccess titleKey="nav.admin_cmdb" />;
  return (
    <Flex vertical gap={16} data-testid="cmdb-admin">
      <SettingsPageHeader
        title={t('nav.admin_cmdb')}
        description={t('setup.page.cmdb.description')}
      />
      <SettingsBlock />
      <TypesBlock />
      <StatesBlock />
      <RelationshipTypesBlock />
      <SourceOrderBlock />
      {can('automation.view') && <CiTriggersBlock />}
    </Flex>
  );
}

/**
 * Triggers on configuration items (WP-053 S5d, REQ-CMDB-023): a CI's state, relationships or
 * downtime can set its own fields. Only "set a field": a CI has no notes.
 */
function CiTriggersBlock() {
  const t = useLabel();
  return (
    <SettingsCard title={t('cmdb.admin.triggers')} testId="cmdb-triggers">
      <TriggersTab recordType="cmdb_ci" actionKinds={['set']} />
    </SettingsCard>
  );
}

function SettingsBlock() {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useCmdbSettings();
  const save = useUpdateCmdbSettings();
  return (
    <SettingsCard title={t('cmdb.title')} testId="cmdb-settings">
      <Space>
        <Switch
          aria-label={t('cmdb.settings.exclude_eol')}
          checked={settings.data?.exclude_eol_from_pickers ?? true}
          loading={save.isPending || settings.isPending}
          onChange={(on) => {
            if (settings.data === undefined) return;
            save.mutate(
              { excludeEol: on, version: settings.data.version },
              {
                onSuccess: () => {
                  void message.success(
                    t(on ? 'cmdb.settings.eol_hidden' : 'cmdb.settings.eol_shown'),
                  );
                },
                onError: reportError,
              },
            );
          }}
          data-testid="cmdb-exclude-eol"
        />
        {t('cmdb.settings.exclude_eol')}
      </Space>
    </SettingsCard>
  );
}

function TypesBlock() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message, modal } = App.useApp();
  const types = useCiTypes();
  const remove = useDeleteCiType();
  const [editing, setEditing] = useState<CiType | 'new' | null>(null);
  const items = types.data?.items ?? [];
  const name = (x: CiType) => nameOf(t, locale, x, 'cmdb_ci_type');
  const parentName = (id: string | null) => {
    const parent = items.find((x) => x.id === id);
    return parent === undefined ? '' : name(parent);
  };
  return (
    <SettingsCard title={t('cmdb.title.types')} testId="cmdb-types">
      <Flex vertical gap={12}>
        <Flex justify="end">
          <WriteButton
            onClick={() => {
              setEditing('new');
            }}
            data-testid="cmdb-type-new"
          >
            {t('cmdb.action.new_type')}
          </WriteButton>
        </Flex>
        <div
          role="region"
          aria-label={t('cmdb.title.types')}
          tabIndex={0}
          style={{ overflowX: 'auto' }}
        >
          <Table<CiType>
            rowKey="id"
            size="small"
            pagination={false}
            loading={types.isPending}
            dataSource={items}
            columns={[
              {
                key: 'name',
                title: t('cmdb.field.name'),
                render: (_, row) => <bdi>{name(row)}</bdi>,
              },
              {
                key: 'code',
                title: t('cmdb.field.api_name'),
                render: (_, row) => (
                  // A code, typed by an admin: always left to right (lane C, #524).
                  <bdi dir="ltr">
                    <Typography.Text code>{row.api_name}</Typography.Text>
                  </bdi>
                ),
              },
              {
                key: 'parent',
                title: t('cmdb.field.parent_id'),
                render: (_, row) => parentName(row.parent_id),
              },
              { key: 'count', title: t('cmdb.count'), render: (_, row) => row.ci_count },
              {
                key: 'actions',
                title: t('cmdb.field.actions'),
                render: (_, row) => (
                  <Space>
                    <Button
                      size="small"
                      onClick={() => {
                        setEditing(row);
                      }}
                      data-testid={`cmdb-type-edit-${row.api_name}`}
                    >
                      {t('actions.edit')}
                    </Button>
                    <Link
                      to={ciTypeFieldsHref(row.id)}
                      aria-label={t('cmdb.fields.open', { type: name(row) })}
                      data-testid={`cmdb-type-fields-${row.api_name}`}
                    >
                      {t('cmdb.fields.tab')}
                    </Link>
                    {!row.built_in && (
                      <Button
                        size="small"
                        danger
                        loading={remove.isPending}
                        onClick={() => {
                          modal.confirm({
                            title: t('cmdb.type_delete_confirm', { name: name(row) }),
                            okText: t('cmdb.action.remove'),
                            okButtonProps: { danger: true },
                            cancelText: t('actions.cancel'),
                            onOk: () =>
                              remove.mutateAsync({ id: row.id, version: row.version }).then(() => {
                                void message.success(t('cmdb.type_removed', { name: name(row) }));
                              }, reportError),
                          });
                        }}
                        data-testid={`cmdb-type-delete-${row.api_name}`}
                      >
                        {t('cmdb.action.remove')}
                      </Button>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </div>
      </Flex>
      {editing !== null && (
        <TypeDialog
          type={editing === 'new' ? null : editing}
          types={items}
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </SettingsCard>
  );
}

function TypeDialog({
  type,
  types,
  onClose,
}: {
  type: CiType | null;
  types: CiType[];
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const create = useCreateCiType();
  const update = useUpdateCiType();
  const [form] = Form.useForm<TypeDraft>();
  const [key] = useState(() => crypto.randomUUID());
  const tree = useMemo(
    () =>
      typeTree(
        types.filter((x) => x.id !== type?.id),
        (x) => nameOf(t, locale, x, 'cmdb_ci_type'),
      ),
    [types, type, t, locale],
  );
  const initial: TypeDraft =
    type === null
      ? { api_name: '', name_en: '' }
      : {
          api_name: type.api_name,
          name_en: type.names.en ?? '',
          name_ar: type.names.ar,
          name_ur: type.names.ur,
          parent_id: type.parent_id ?? undefined,
        };
  const done = () => {
    void message.success(t(type === null ? 'cmdb.type_added' : 'cmdb.type_saved'));
    onClose();
  };
  const submit = (draft: TypeDraft) => {
    if (type === null) {
      create.mutate(
        {
          body: {
            api_name: draft.api_name.trim(),
            names: names(draft),
            parent_id: draft.parent_id ?? null,
          },
          key,
        },
        { onSuccess: done, onError: reportError },
      );
      return;
    }
    const own = names(draft);
    update.mutate(
      {
        id: type.id,
        version: type.version,
        changes: {
          ...(type.built_in && own.en === '' ? {} : { names: own }),
          ...(type.built_in ? {} : { parent_id: draft.parent_id ?? null }),
        },
      },
      { onSuccess: done, onError: reportError },
    );
  };
  return (
    <Modal
      open
      title={type === null ? t('cmdb.action.new_type') : t('actions.edit')}
      onCancel={onClose}
      okText={t('actions.save')}
      okButtonProps={{ loading: create.isPending || update.isPending }}
      onOk={() => {
        form.submit();
      }}
    >
      <Form<TypeDraft> form={form} layout="vertical" initialValues={initial} onFinish={submit}>
        <Form.Item name="api_name" label={t('cmdb.field.api_name')} rules={[{ required: true }]}>
          <Input disabled={type !== null} data-testid="cmdb-type-code" />
        </Form.Item>
        <Form.Item
          name="name_en"
          label={t('cmdb.field.names_en')}
          rules={[{ required: !type?.built_in }]}
        >
          <Input data-testid="cmdb-type-name" />
        </Form.Item>
        <Flex gap={12}>
          <Form.Item name="name_ar" label={t('cmdb.field.names_ar')} style={{ flex: 1 }}>
            <Input dir="rtl" />
          </Form.Item>
          <Form.Item name="name_ur" label={t('cmdb.field.names_ur')} style={{ flex: 1 }}>
            <Input dir="rtl" />
          </Form.Item>
        </Flex>
        {!type?.built_in && (
          <Form.Item name="parent_id" label={t('cmdb.field.parent_id')}>
            <TreeSelect allowClear treeDefaultExpandAll treeData={tree} />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

function StatesBlock() {
  const t = useLabel();
  const { locale } = useAppearance();
  const states = useCiStates();
  const { message, modal } = App.useApp();
  const create = useCreateCiState();
  const remove = useDeleteCiState();
  const [adding, setAdding] = useState(false);
  const [form] = Form.useForm<{
    api_name: string;
    name_en: string;
    category: 'active' | 'end_of_life';
  }>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  return (
    <SettingsCard title={t('cmdb.title.states')} testId="cmdb-states">
      <Flex vertical gap={12}>
        <Flex justify="end">
          <WriteButton
            onClick={() => {
              setAdding(true);
            }}
            data-testid="cmdb-state-new"
          >
            {t('cmdb.action.new_state')}
          </WriteButton>
        </Flex>
        <Table<CiState>
          rowKey="id"
          size="small"
          pagination={false}
          loading={states.isPending}
          dataSource={states.data?.items ?? []}
          columns={[
            {
              key: 'name',
              title: t('cmdb.field.name'),
              render: (_, row) => <bdi>{nameOf(t, locale, row, 'cmdb_ci_state')}</bdi>,
            },
            {
              key: 'category',
              title: t('cmdb.field.category'),
              render: (_, row) => t(`cmdb_state_category.${row.category}`),
            },
            {
              key: 'actions',
              title: t('cmdb.field.actions'),
              render: (_, row) =>
                !row.built_in && (
                  <Button
                    size="small"
                    danger
                    onClick={() => {
                      const shown = nameOf(t, locale, row, 'cmdb_ci_state');
                      modal.confirm({
                        title: t('cmdb.state_delete_confirm', { name: shown }),
                        okText: t('cmdb.action.remove'),
                        okButtonProps: { danger: true },
                        cancelText: t('actions.cancel'),
                        onOk: () =>
                          remove.mutateAsync({ id: row.id, version: row.version }).then(() => {
                            void message.success(t('cmdb.state_removed', { name: shown }));
                          }, reportError),
                      });
                    }}
                  >
                    {t('cmdb.action.remove')}
                  </Button>
                ),
            },
          ]}
        />
      </Flex>
      {adding && (
        <Modal
          open
          title={t('cmdb.action.new_state')}
          onCancel={() => {
            setAdding(false);
          }}
          okText={t('actions.save')}
          okButtonProps={{ loading: create.isPending }}
          onOk={() => {
            form.submit();
          }}
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={{ category: 'active' }}
            onFinish={(draft) => {
              create.mutate(
                {
                  body: {
                    api_name: draft.api_name.trim(),
                    names: { en: draft.name_en.trim() },
                    category: draft.category,
                    position: 100,
                  },
                  key,
                },
                {
                  onSuccess: () => {
                    setAdding(false);
                    setKey(crypto.randomUUID());
                    form.resetFields();
                  },
                  onError: (error) => {
                    setKey(crypto.randomUUID());
                    reportError(error);
                  },
                },
              );
            }}
          >
            <Form.Item
              name="api_name"
              label={t('cmdb.field.api_name')}
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="name_en" label={t('cmdb.field.names_en')} rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item name="category" label={t('cmdb.field.category')}>
              <Select
                options={(['active', 'end_of_life'] as const).map((c) => ({
                  value: c,
                  label: t(`cmdb_state_category.${c}`),
                }))}
              />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </SettingsCard>
  );
}
