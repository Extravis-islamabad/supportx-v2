import {
  Button,
  Card,
  Flex,
  Form,
  Modal,
  Popconfirm,
  Skeleton,
  Space,
  Tag,
  Tree,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  ApiError,
  useIncidentCategories,
  useIncidentCategoryChange,
  useUnits,
  type IncidentCategory,
  type Labels,
} from '@supportx/api-client';
import { EmptyText, reportError, useAppearance, useLabel, WriteButton } from '@supportx/ui';
import { App } from 'antd';

import { categoryLabel } from '../../incidents/labels';
import { GroupPicker } from '../../incidents/pickers';
import { cleanLabels, fieldMessages } from './helpers';
import { LabelsFields, Problems } from './shared';

type Editing =
  { kind: 'create'; parent: IncidentCategory | null } | { kind: 'update'; node: IncidentCategory };

const LEVEL_NAMES = ['category', 'subcategory', 'item'] as const;

/**
 * The category › subcategory › item tree (REQ-INC-006): add at any level up to three, rename
 * and translate, suggest a group, retire and bring back. Retired nodes stay in the tree,
 * marked: records that use them keep showing them (AC3); new incidents cannot pick them.
 */
export function CategoriesTab() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const categories = useIncidentCategories();
  const groups = useUnits('groups');
  const change = useIncidentCategoryChange();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [names, setNames] = useState<Labels>({});
  const [group, setGroup] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const nodes = useMemo(() => categories.data ?? [], [categories.data]);

  const start = (next: Editing) => {
    setProblems([]);
    setEditing(next);
    setNames(next.kind === 'update' ? (next.node.labels ?? {}) : {});
    setGroup(next.kind === 'update' ? next.node.default_group_id : null);
  };
  const done = () => {
    void message.success(t('settings.saved'));
    setEditing(null);
  };
  const failed = (error: unknown) => {
    const found = fieldMessages(t, error);
    if (found.length > 0) setProblems(found);
    else if (error instanceof ApiError && error.isConflict) {
      void message.warning(t('settings.changed_elsewhere'));
      setEditing(null);
    } else reportError(error);
  };
  const setDisabled = (node: IncidentCategory, disabled: boolean) => {
    change.mutate(
      { kind: 'update', id: node.id, version: node.version, body: { disabled } },
      { onSuccess: done, onError: failed },
    );
  };

  const tree = useMemo(() => {
    interface Node {
      key: string;
      node: IncidentCategory;
      children: Node[];
    }
    const byParent = new Map<string | null, Node[]>();
    for (const n of nodes) {
      const list = byParent.get(n.parent_id) ?? [];
      list.push({ key: n.id, node: n, children: [] });
      byParent.set(n.parent_id, list);
    }
    const attach = (list: Node[]): Node[] =>
      list.map((entry) => ({ ...entry, children: attach(byParent.get(entry.key) ?? []) }));
    return attach(byParent.get(null) ?? []);
  }, [nodes]);

  const shipped = (node: IncidentCategory) =>
    node.code === null ? null : t(`work_item_category.${node.code}`);
  const groupName = (id: string | null) => groups.data?.find((g) => g.id === id)?.name;

  return (
    <Card
      title={t('settings.categories')}
      extra={
        <WriteButton
          onClick={() => {
            start({ kind: 'create', parent: null });
          }}
          data-testid="cat-add-root"
        >
          {t('settings.add_category')}
        </WriteButton>
      }
      data-testid="settings-categories"
    >
      <Typography.Paragraph type="secondary">{t('settings.categories_help')}</Typography.Paragraph>
      {categories.data === undefined ? (
        // The tree mounts with its nodes, so it opens expanded (QA BUG-06).
        <Skeleton active />
      ) : nodes.length === 0 ? (
        <EmptyText>{t('settings.no_values')}</EmptyText>
      ) : (
        <Tree
          blockNode
          defaultExpandAll
          selectable={false}
          treeData={tree}
          fieldNames={{ key: 'key', children: 'children', title: 'key' }}
          titleRender={(entry) => {
            const node = (entry as unknown as { node: IncidentCategory }).node;
            const suggested = groupName(node.default_group_id);
            return (
              <Flex
                justify="space-between"
                align="center"
                wrap
                gap={8}
                data-testid={`cat-${node.id}`}
              >
                <Flex gap={8} align="center" wrap>
                  <bdi dir="auto">{categoryLabel(t, node, locale)}</bdi>
                  <Typography.Text type="secondary">
                    {t(`categories.level.${LEVEL_NAMES[node.level - 1] ?? 'item'}`)}
                  </Typography.Text>
                  {node.disabled && <Tag>{t('settings.retired')}</Tag>}
                  {suggested !== undefined && (
                    <Tag>{t('settings.suggests_group', { group: suggested })}</Tag>
                  )}
                </Flex>
                <Space size={0}>
                  {node.level < 3 && !node.disabled && (
                    <Button
                      type="link"
                      size="small"
                      onClick={() => {
                        start({ kind: 'create', parent: node });
                      }}
                      data-testid={`cat-add-${node.id}`}
                    >
                      {t(node.level === 1 ? 'settings.add_subcategory' : 'settings.add_item')}
                    </Button>
                  )}
                  <Button
                    type="link"
                    size="small"
                    onClick={() => {
                      start({ kind: 'update', node });
                    }}
                    data-testid={`cat-edit-${node.id}`}
                  >
                    {t('settings.rename')}
                  </Button>
                  {node.disabled ? (
                    <Button
                      type="link"
                      size="small"
                      onClick={() => {
                        setDisabled(node, false);
                      }}
                      data-testid={`cat-restore-${node.id}`}
                    >
                      {t('settings.bring_back')}
                    </Button>
                  ) : (
                    <Popconfirm
                      title={t('settings.retire_confirm', { name: categoryLabel(t, node, locale) })}
                      description={t('settings.retire_category_explained')}
                      okText={t('settings.retire')}
                      cancelText={t('actions.cancel')}
                      onConfirm={() => {
                        setDisabled(node, true);
                      }}
                    >
                      <Button type="link" size="small" data-testid={`cat-retire-${node.id}`}>
                        {t('settings.retire')}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              </Flex>
            );
          }}
        />
      )}
      <Modal
        open={editing !== null}
        title={
          editing === null
            ? ''
            : editing.kind === 'update'
              ? t('settings.rename_value', { name: categoryLabel(t, editing.node, locale) })
              : editing.parent === null
                ? t('settings.add_category')
                : t('settings.add_under', { name: categoryLabel(t, editing.parent, locale) })
        }
        okText={t('actions.save')}
        cancelText={t('actions.cancel')}
        confirmLoading={change.isPending}
        onCancel={() => {
          setEditing(null);
        }}
        onOk={() => {
          if (editing === null) return;
          const labels = cleanLabels(names);
          if (editing.kind === 'create') {
            change.mutate(
              {
                kind: 'create',
                parentId: editing.parent?.id ?? null,
                labels: labels ?? {},
                defaultGroupId: group,
              },
              { onSuccess: done, onError: failed },
            );
          } else {
            change.mutate(
              {
                kind: 'update',
                id: editing.node.id,
                version: editing.node.version,
                body: {
                  labels: labels ?? (editing.node.code === null ? {} : null),
                  default_group_id: group,
                },
              },
              { onSuccess: done, onError: failed },
            );
          }
        }}
        destroyOnHidden
        data-testid="cat-dialog"
      >
        <Problems problems={problems} testId="cat-problems" />
        <Form layout="vertical" component="div">
          {editing?.kind === 'update' && shipped(editing.node) !== null && (
            <Typography.Paragraph type="secondary">
              {t('settings.shipped_name_hint', { name: shipped(editing.node) ?? '' })}
            </Typography.Paragraph>
          )}
          <LabelsFields value={names} onChange={setNames} testId="cat-name" />
          <Form.Item
            label={t('settings.default_group')}
            htmlFor="cat-group"
            help={t('settings.default_group_help')}
          >
            <GroupPicker
              id="cat-group"
              value={group}
              onChange={setGroup}
              testId="cat-group"
              ariaLabel={t('settings.default_group')}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
