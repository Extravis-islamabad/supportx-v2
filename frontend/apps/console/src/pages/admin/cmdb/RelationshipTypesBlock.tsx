import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons';
import {
  App,
  Button,
  Checkbox,
  Flex,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  useCiTypes,
  useCreateRelationshipType,
  useDeleteRelationshipType,
  useRelationshipTypes,
  useUpdateRelationshipType,
  type RelationshipRule,
  type RelationshipType,
} from '@supportx/api-client';
import {
  SettingsCard,
  WriteButton,
  lengthLimit,
  reportError,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { NAME_MAX } from '../../cmdb/form';
import { nameOf, typeTree } from '../../cmdb/names';
import { relationshipName } from '../../cmdb/map/words';

const LANGUAGES = ['en', 'ar', 'ur'] as const;

interface Draft {
  code: string;
  forward: Partial<Record<(typeof LANGUAGES)[number], string>>;
  inverse: Partial<Record<(typeof LANGUAGES)[number], string>>;
  carries_impact: boolean;
  rules: { from_ci_type_id?: string; to_ci_type_id?: string; suggested?: boolean }[];
}

const trimmed = (names: Draft['forward']): Record<string, string> =>
  Object.fromEntries(
    LANGUAGES.flatMap((lang) => {
      const value = names[lang]?.trim() ?? '';
      return value === '' ? [] : [[lang, value]];
    }),
  );

/**
 * Admin › CMDB › Relationship types (template E; REQ-CMDB-006): the built-in types and the
 * tenant's own, each with a name for both directions in English, Arabic and Urdu, whether it
 * carries impact, and the CI types it may join (none: any two). A type still in use cannot be
 * removed: the refusal says how many relationships use it.
 */
export function RelationshipTypesBlock() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message, modal } = App.useApp();
  const types = useRelationshipTypes();
  const remove = useDeleteRelationshipType();
  const [editing, setEditing] = useState<RelationshipType | 'new' | null>(null);
  const items = types.data?.items ?? [];
  return (
    <SettingsCard title={t('cmdb.title.relationship_types')} testId="cmdb-relationship-types">
      <Flex vertical gap={12}>
        <Flex justify="end">
          <WriteButton
            onClick={() => {
              setEditing('new');
            }}
            data-testid="cmdb-relationship-type-new"
          >
            {t('cmdb.action.new_relationship_type')}
          </WriteButton>
        </Flex>
        <div
          role="region"
          aria-label={t('cmdb.title.relationship_types')}
          tabIndex={0}
          style={{ overflowX: 'auto' }}
        >
          <Table<RelationshipType>
            rowKey="id"
            size="small"
            pagination={false}
            loading={types.isPending}
            dataSource={items}
            columns={[
              {
                key: 'forward',
                title: t('cmdb.relationship_type.forward'),
                render: (_, row) => <bdi>{relationshipName(t, locale, row, 'forward')}</bdi>,
              },
              {
                key: 'inverse',
                title: t('cmdb.relationship_type.inverse'),
                render: (_, row) => <bdi>{relationshipName(t, locale, row, 'inverse')}</bdi>,
              },
              {
                key: 'impact',
                title: t('cmdb.relationship_type.carries_impact'),
                render: (_, row) => t(row.carries_impact ? 'cmdb.yes' : 'cmdb.no'),
              },
              {
                key: 'rules',
                title: t('cmdb.relationship_type.rules'),
                render: (_, row) =>
                  row.rules.length === 0
                    ? t('cmdb.relationship_type.any_types')
                    : t('cmdb.relationship_type.rule_count', { count: row.rules.length }),
              },
              {
                key: 'count',
                title: t('cmdb.relationship_type.in_use'),
                render: (_, row) => row.relationship_count,
              },
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
                      data-testid={`cmdb-relationship-type-edit-${row.code}`}
                    >
                      {t('actions.edit')}
                    </Button>
                    {!row.built_in && (
                      <Button
                        size="small"
                        danger
                        onClick={() => {
                          const name = relationshipName(t, locale, row, 'forward');
                          modal.confirm({
                            title: t('cmdb.relationship_type.delete_confirm', { name }),
                            okText: t('cmdb.action.remove'),
                            okButtonProps: { danger: true },
                            cancelText: t('actions.cancel'),
                            onOk: () =>
                              remove.mutateAsync({ id: row.id, version: row.version }).then(() => {
                                void message.success(t('cmdb.relationship_type.removed', { name }));
                              }, reportError),
                          });
                        }}
                        data-testid={`cmdb-relationship-type-delete-${row.code}`}
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
          onClose={() => {
            setEditing(null);
          }}
        />
      )}
    </SettingsCard>
  );
}

function TypeDialog({ type, onClose }: { type: RelationshipType | null; onClose: () => void }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const ciTypes = useCiTypes();
  const create = useCreateRelationshipType();
  const update = useUpdateRelationshipType();
  const [form] = Form.useForm<Draft>();
  const [key] = useState(() => crypto.randomUUID());
  const tree = useMemo(
    () => typeTree(ciTypes.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type')),
    [ciTypes.data, t, locale],
  );
  // A tenant's own type needs both names in every language; a built-in one may leave them out.
  const required = type?.built_in !== true;
  const initial: Draft =
    type === null
      ? { code: '', forward: {}, inverse: {}, carries_impact: true, rules: [] }
      : {
          code: type.code,
          forward: type.names_forward,
          inverse: type.names_inverse,
          carries_impact: type.carries_impact,
          rules: type.rules.map((r) => ({ ...r })),
        };
  const done = () => {
    void message.success(
      t(type === null ? 'cmdb.relationship_type.added' : 'cmdb.relationship_type.saved'),
    );
    onClose();
  };
  const submit = (draft: Draft) => {
    const rules: RelationshipRule[] = draft.rules.flatMap((r) =>
      r.from_ci_type_id === undefined || r.to_ci_type_id === undefined
        ? []
        : [
            {
              from_ci_type_id: r.from_ci_type_id,
              to_ci_type_id: r.to_ci_type_id,
              suggested: r.suggested ?? false,
            },
          ],
    );
    const forward = trimmed(draft.forward);
    const inverse = trimmed(draft.inverse);
    if (type === null) {
      create.mutate(
        {
          key,
          body: {
            code: draft.code.trim(),
            names_forward: forward,
            names_inverse: inverse,
            carries_impact: draft.carries_impact,
            rules,
          },
        },
        { onSuccess: done, onError: reportError },
      );
      return;
    }
    update.mutate(
      {
        id: type.id,
        version: type.version,
        changes: {
          names_forward: forward,
          names_inverse: inverse,
          carries_impact: draft.carries_impact,
          rules,
        },
      },
      { onSuccess: done, onError: reportError },
    );
  };
  const nameFields = (direction: 'forward' | 'inverse') => (
    <Flex gap={12} wrap>
      {LANGUAGES.map((lang) => (
        <Form.Item
          key={lang}
          name={[direction, lang]}
          label={t(`cmdb.relationship_type.${direction}_${lang}`)}
          rules={[{ required, whitespace: true, message: t('errors.field.required') }]}
          style={{ flex: '1 1 160px' }}
        >
          <Input
            dir={lang === 'en' ? undefined : 'rtl'}
            count={lengthLimit(NAME_MAX)}
            data-testid={`cmdb-relationship-type-${direction}-${lang}`}
          />
        </Form.Item>
      ))}
    </Flex>
  );
  return (
    <Modal
      open
      width={720}
      title={type === null ? t('cmdb.action.new_relationship_type') : t('actions.edit')}
      onCancel={onClose}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      okButtonProps={{
        loading: create.isPending || update.isPending,
        'data-testid': 'cmdb-relationship-type-save',
      }}
      onOk={() => {
        form.submit();
      }}
      destroyOnHidden
    >
      <Form<Draft> form={form} layout="vertical" initialValues={initial} onFinish={submit}>
        <Form.Item
          name="code"
          label={t('cmdb.field.api_name')}
          rules={[{ required: true, whitespace: true, message: t('errors.field.required') }]}
        >
          <Input dir="ltr" disabled={type !== null} data-testid="cmdb-relationship-type-code" />
        </Form.Item>
        {nameFields('forward')}
        {nameFields('inverse')}
        <Form.Item
          name="carries_impact"
          label={t('cmdb.relationship_type.carries_impact')}
          valuePropName="checked"
        >
          <Switch data-testid="cmdb-relationship-type-impact" />
        </Form.Item>
        <Typography.Text strong>{t('cmdb.relationship_type.rules')}</Typography.Text>
        <Typography.Paragraph type="secondary">
          {t('cmdb.relationship_type.rules_help')}
        </Typography.Paragraph>
        <Form.List name="rules">
          {(fields, { add, remove }) => (
            <Flex vertical gap={8}>
              {fields.map((field) => (
                <Flex key={field.key} gap={8} wrap align="center">
                  <Form.Item
                    name={[field.name, 'from_ci_type_id']}
                    rules={[{ required: true, message: t('errors.field.required') }]}
                    style={{ flex: '1 1 180px', marginBottom: 0 }}
                  >
                    <TreeSelect
                      aria-label={t('cmdb.relationship_type.rule_from')}
                      placeholder={t('cmdb.relationship_type.rule_from')}
                      treeDefaultExpandAll
                      treeData={tree}
                    />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, 'to_ci_type_id']}
                    rules={[{ required: true, message: t('errors.field.required') }]}
                    style={{ flex: '1 1 180px', marginBottom: 0 }}
                  >
                    <TreeSelect
                      aria-label={t('cmdb.relationship_type.rule_to')}
                      placeholder={t('cmdb.relationship_type.rule_to')}
                      treeDefaultExpandAll
                      treeData={tree}
                    />
                  </Form.Item>
                  <Form.Item
                    name={[field.name, 'suggested']}
                    valuePropName="checked"
                    style={{ marginBottom: 0 }}
                  >
                    <Checkbox>{t('cmdb.relationship_type.suggested')}</Checkbox>
                  </Form.Item>
                  <Button
                    type="text"
                    icon={<MinusCircleOutlined />}
                    aria-label={t('cmdb.relationship_type.rule_remove')}
                    onClick={() => {
                      remove(field.name);
                    }}
                  />
                </Flex>
              ))}
              <Button
                icon={<PlusOutlined />}
                onClick={() => {
                  add({ suggested: false });
                }}
                disabled={fields.length >= 100}
                data-testid="cmdb-relationship-type-rule-add"
              >
                {t('cmdb.relationship_type.rule_add')}
              </Button>
            </Flex>
          )}
        </Form.List>
      </Form>
    </Modal>
  );
}
