import {
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Table,
  Tag,
  TreeSelect,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import type {
  AssetLifeCycle,
  AssetProductType,
  AssetProductTypePatch,
  AssetTypeCategory,
  AssetTypeKind,
} from '@supportx/api-client';
import { lengthLimit, useAppearance, useLabel, WriteButton } from '@supportx/ui';

import { LabelsFields, Problems } from '../incidents/shared';
import { codeFrom, nameOf, useCatalogueSave, type Names } from './shared';
import { typeTree, type TypeNode } from './tree';

const CATEGORIES: AssetTypeCategory[] = ['it', 'non_it'];
const KINDS: AssetTypeKind[] = ['asset', 'component', 'consumable'];

/** `id` and every type below it: a type cannot move under itself. */
function below(id: string, types: AssetProductType[]): Set<string> {
  const found = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const type of types) {
      if (type.parent_id !== null && found.has(type.parent_id) && !found.has(type.id)) {
        found.add(type.id);
        grew = true;
      }
    }
  }
  return found;
}

interface Draft {
  names: Names;
  parentId: string | null;
  category: AssetTypeCategory;
  kind: AssetTypeKind;
  lifeCycleId: string | null;
  tagPattern: string;
  ackRequired: boolean;
  description: string;
}

/**
 * Product types in a tree (D-141): a top-level type says whether it is IT or not and whether it
 * is an asset, a component or a consumable; the types below inherit both, so only top-level
 * types show those choices. Only IT assets count toward the licence's asset limit, and the
 * screen says so. A type with types or products under it cannot be deleted.
 */
export function TypesTab({
  types,
  lifeCycles,
}: {
  types: AssetProductType[];
  lifeCycles: AssetLifeCycle[];
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { run, problems, clear, pending } = useCatalogueSave();
  const [editing, setEditing] = useState<AssetProductType | 'new' | null>(null);
  const [draft, setDraft] = useState<Draft>();
  const [key, setKey] = useState(() => crypto.randomUUID());
  const tree = useMemo(() => typeTree(types), [types]);
  const lifeCycleName = (id: string | null) => {
    const cycle = lifeCycles.find((c) => (id === null ? c.is_default : c.id === id));
    return cycle === undefined ? '' : nameOf(cycle.names, locale);
  };
  const open = (type: AssetProductType | 'new', parent: AssetProductType | null = null) => {
    clear();
    setKey(crypto.randomUUID());
    setEditing(type);
    setDraft(
      type === 'new'
        ? {
            names: {},
            parentId: parent?.id ?? null,
            category: parent?.category ?? 'it',
            kind: parent?.kind ?? 'asset',
            lifeCycleId: null,
            tagPattern: '',
            ackRequired: false,
            description: '',
          }
        : {
            names: type.names,
            parentId: type.parent_id,
            category: type.category,
            kind: type.kind,
            lifeCycleId: type.life_cycle_id,
            tagPattern: type.tag_pattern ?? '',
            ackRequired: type.ack_required,
            description: type.description ?? '',
          },
    );
  };
  const close = () => {
    clear();
    setEditing(null);
  };
  const save = () => {
    if (draft === undefined || editing === null) return;
    const top = draft.parentId === null;
    const tagPattern = draft.tagPattern.trim() === '' ? null : draft.tagPattern.trim();
    const description = draft.description.trim() === '' ? null : draft.description.trim();
    if (editing === 'new') {
      run(
        {
          kind: 'create_product_type',
          key,
          body: {
            api_name: codeFrom(draft.names.en ?? '', new Set(types.map((x) => x.api_name)), 'type'),
            names: draft.names,
            parent_id: draft.parentId,
            ...(top && { category: draft.category, kind: draft.kind }),
            life_cycle_id: draft.lifeCycleId,
            tag_pattern: tagPattern,
            ack_required: draft.ackRequired,
            description,
          },
        },
        close,
      );
      return;
    }
    // Only what changed: a nullable field sent as null means "back to the default".
    const body: AssetProductTypePatch = { names: draft.names };
    if (draft.parentId !== editing.parent_id) body.parent_id = draft.parentId;
    if (top && draft.category !== editing.category) body.category = draft.category;
    if (top && draft.kind !== editing.kind) body.kind = draft.kind;
    if (draft.lifeCycleId !== editing.life_cycle_id) body.life_cycle_id = draft.lifeCycleId;
    if (tagPattern !== editing.tag_pattern) body.tag_pattern = tagPattern;
    if (draft.ackRequired !== editing.ack_required) body.ack_required = draft.ackRequired;
    if (description !== editing.description) body.description = description;
    run({ kind: 'product_type', id: editing.id, version: editing.version, body }, close, close);
  };
  const excluded = editing !== null && editing !== 'new' ? below(editing.id, types) : new Set();
  const parentChoices = (nodes: TypeNode[]): object[] =>
    nodes
      .filter((node) => !excluded.has(node.id))
      .map((node) => ({
        value: node.id,
        title: nameOf(node.names, locale),
        children: parentChoices(node.children ?? []),
      }));
  return (
    <Card
      title={t('assets.admin.product_types')}
      extra={
        <WriteButton
          onClick={() => {
            open('new');
          }}
          data-testid="asset-type-add"
        >
          {t('assets.admin.add_top_type')}
        </WriteButton>
      }
      data-testid="asset-types"
    >
      <Typography.Paragraph type="secondary">{t('assets.admin.types_help')}</Typography.Paragraph>
      {editing === null && <Problems problems={problems} testId="asset-types-problems" />}
      <Table<TypeNode>
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={tree}
        columns={[
          {
            key: 'name',
            title: t('settings.name'),
            render: (_: unknown, type: TypeNode) => (
              <bdi dir="auto" data-testid={`asset-type-name-${type.api_name}`}>
                {nameOf(type.names, locale)}
              </bdi>
            ),
          },
          {
            key: 'category',
            title: t('assets.admin.type_category'),
            render: (_: unknown, type: TypeNode) => (
              <Flex gap={4} wrap>
                <Tag>{t(`asset_type_category.${type.category}`)}</Tag>
                <Tag>{t(`asset_type_kind.${type.kind}`)}</Tag>
              </Flex>
            ),
          },
          {
            key: 'life_cycle',
            title: t('assets.admin.life_cycle'),
            render: (_: unknown, type: TypeNode) => (
              <bdi dir="auto">{lifeCycleName(type.life_cycle_id)}</bdi>
            ),
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('assets.admin.actions')}</span>,
            render: (_: unknown, type: TypeNode) => (
              <Flex gap={4} justify="end" wrap>
                <Button
                  type="link"
                  onClick={() => {
                    open('new', type);
                  }}
                  data-testid={`asset-type-add-below-${type.api_name}`}
                >
                  {t('assets.admin.add_below')}
                </Button>
                <Button
                  type="link"
                  onClick={() => {
                    open(type);
                  }}
                  data-testid={`asset-type-edit-${type.api_name}`}
                >
                  {t('actions.edit')}
                </Button>
                {type.children === undefined && (
                  <Popconfirm
                    title={t('assets.admin.delete_confirm', { name: nameOf(type.names, locale) })}
                    okText={t('actions.delete')}
                    cancelText={t('actions.cancel')}
                    onConfirm={() => {
                      run({ kind: 'delete_product_type', id: type.id, version: type.version });
                    }}
                  >
                    <Button type="link" danger data-testid={`asset-type-delete-${type.api_name}`}>
                      {t('actions.delete')}
                    </Button>
                  </Popconfirm>
                )}
              </Flex>
            ),
          },
        ]}
      />
      <Modal
        open={editing !== null}
        title={editing === 'new' ? t('assets.admin.add_type') : t('assets.admin.edit_type')}
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        onOk={save}
        onCancel={close}
        confirmLoading={pending}
        destroyOnHidden
        data-testid="asset-type-dialog"
      >
        {draft !== undefined && editing !== null && (
          <Form layout="vertical">
            <Problems problems={problems} testId="asset-type-problems" />
            <LabelsFields
              value={draft.names}
              onChange={(names) => {
                setDraft({ ...draft, names });
              }}
              testId="asset-type-name"
            />
            <Form.Item label={t('assets.admin.parent_type')} htmlFor="asset-type-parent">
              <TreeSelect
                id="asset-type-parent"
                aria-label={t('assets.admin.parent_type')}
                allowClear
                placeholder={t('assets.admin.top_level')}
                value={draft.parentId ?? undefined}
                treeData={parentChoices(tree)}
                treeDefaultExpandAll
                onChange={(id: string | undefined) => {
                  const parent = types.find((x) => x.id === id);
                  setDraft({
                    ...draft,
                    parentId: id ?? null,
                    // Inherited from the new parent (D-141); the server does the same.
                    category: parent?.category ?? draft.category,
                    kind: parent?.kind ?? draft.kind,
                  });
                }}
                data-testid="asset-type-parent"
              />
            </Form.Item>
            {draft.parentId === null ? (
              <Flex gap={16} wrap>
                <Form.Item label={t('assets.admin.type_category')} htmlFor="asset-type-category">
                  <Select
                    id="asset-type-category"
                    aria-label={t('assets.admin.type_category')}
                    value={draft.category}
                    onChange={(category: AssetTypeCategory) => {
                      setDraft({ ...draft, category });
                    }}
                    options={CATEGORIES.map((code) => ({
                      value: code,
                      label: t(`asset_type_category.${code}`),
                    }))}
                    style={{ minWidth: 160 }}
                    data-testid="asset-type-category"
                  />
                </Form.Item>
                <Form.Item label={t('assets.admin.type_kind')} htmlFor="asset-type-kind">
                  <Select
                    id="asset-type-kind"
                    aria-label={t('assets.admin.type_kind')}
                    value={draft.kind}
                    onChange={(kind: AssetTypeKind) => {
                      setDraft({ ...draft, kind });
                    }}
                    options={KINDS.map((code) => ({
                      value: code,
                      label: t(`asset_type_kind.${code}`),
                    }))}
                    style={{ minWidth: 160 }}
                    data-testid="asset-type-kind"
                  />
                </Form.Item>
              </Flex>
            ) : (
              <Typography.Paragraph type="secondary" data-testid="asset-type-inherited">
                {t('assets.admin.inherited', {
                  category: t(`asset_type_category.${draft.category}`),
                  kind: t(`asset_type_kind.${draft.kind}`),
                })}
              </Typography.Paragraph>
            )}
            {draft.category === 'it' && draft.kind === 'asset' && (
              <Typography.Paragraph type="secondary" data-testid="asset-type-counts">
                {t('assets.admin.counts_toward_limit')}
              </Typography.Paragraph>
            )}
            <Form.Item label={t('assets.admin.life_cycle')} htmlFor="asset-type-life-cycle">
              <Select
                id="asset-type-life-cycle"
                aria-label={t('assets.admin.life_cycle')}
                allowClear
                placeholder={t('assets.admin.default_life_cycle')}
                value={draft.lifeCycleId ?? undefined}
                onChange={(id: string | undefined) => {
                  setDraft({ ...draft, lifeCycleId: id ?? null });
                }}
                options={lifeCycles.map((c) => ({ value: c.id, label: nameOf(c.names, locale) }))}
                data-testid="asset-type-life-cycle"
              />
            </Form.Item>
            <Form.Item
              label={t('assets.admin.tag_pattern')}
              htmlFor="asset-type-tag"
              extra={
                <Typography.Text type="secondary">
                  {t('assets.admin.type_tag_help')}
                </Typography.Text>
              }
            >
              <Input
                id="asset-type-tag"
                dir="ltr"
                count={lengthLimit(40)}
                value={draft.tagPattern}
                onChange={(event) => {
                  setDraft({ ...draft, tagPattern: event.target.value });
                }}
                data-testid="asset-type-tag"
              />
            </Form.Item>
            <Form.Item label={t('assets.admin.description')} htmlFor="asset-type-description">
              <Input.TextArea
                id="asset-type-description"
                dir="auto"
                rows={2}
                count={lengthLimit(2000)}
                value={draft.description}
                onChange={(event) => {
                  setDraft({ ...draft, description: event.target.value });
                }}
              />
            </Form.Item>
            <Checkbox
              checked={draft.ackRequired}
              onChange={(event) => {
                setDraft({ ...draft, ackRequired: event.target.checked });
              }}
              data-testid="asset-type-ack"
            >
              {t('assets.admin.ack_required')}
            </Checkbox>
          </Form>
        )}
      </Modal>
    </Card>
  );
}
