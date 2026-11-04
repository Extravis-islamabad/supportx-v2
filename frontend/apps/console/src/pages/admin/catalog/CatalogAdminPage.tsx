import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  StarFilled,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Card,
  Flex,
  Input,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tooltip,
  Typography,
  theme,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  ApiError,
  useCatalogCategories,
  useCatalogItemList,
  useCatalogSearch,
  useCatalogSettings,
  useCatalogSettingsChange,
  useCatalogStarter,
  useCopyCatalogItem,
  useDeleteCatalogItem,
  usePublishCatalogStarter,
  useUnits,
  useUpdateCatalogCategory,
  useUpdateCatalogItem,
  type CatalogCategory,
  type CatalogItem,
  type CatalogItemStatus,
} from '@supportx/api-client';
import {
  NoAccess,
  PageHeader,
  ToneTag,
  markHandled,
  reportError,
  textIn,
  useAccess,
  useAppearance,
  useLabel,
  useLicence,
  type Tone,
} from '@supportx/ui';

import { CategoryDialog } from './CategoryDialog';
import { categoryPaths, childrenOf } from './tree';

const STATUS_TONES: Record<CatalogItemStatus, Tone> = {
  draft: 'default',
  published: 'success',
  retired: 'warning',
};
const FILTERS = ['all', 'draft', 'published', 'retired'] as const;
type Filter = (typeof FILTERS)[number];

/** An item's status as a tag (plan D3), with its planned change when one is set. */
export function StatusTag({ item }: { item: CatalogItem }) {
  const t = useLabel();
  return (
    <ToneTag tone={STATUS_TONES[item.status]} testId={`cat-status-${item.id}`}>
      {t(`catalog_item_status.${item.status}`)}
    </ToneTag>
  );
}

/**
 * Admin › Service catalog (WP-031 plan D1, D3, D4, D11, D13): the category tree on one side, the
 * items on the other (search, status filter, order, featured), the starter catalog's "choose a
 * group and publish" banner (D-138) and the tenant's catalog setting. Live: every change anyone
 * makes arrives through `service_catalog.changed` (ConsoleLayout).
 */
export function CatalogAdminPage() {
  const t = useLabel();
  const { can } = useAccess();
  const licence = useLicence();
  if (!licence.has('service_request') || !can('catalog_items.manage')) {
    return <NoAccess titleKey="nav.admin_catalog" />;
  }
  return <CatalogAdmin title={t('nav.admin_catalog')} />;
}

function CatalogAdmin({ title }: { title: string }) {
  const t = useLabel();
  const navigate = useNavigate();
  const [category, setCategory] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [dialog, setDialog] = useState<{ category?: CatalogCategory; parent?: string } | null>(
    null,
  );
  const categories = useCatalogCategories();
  const listed = useCatalogItemList({
    category_id: category ?? undefined,
    status: filter === 'all' ? undefined : [filter],
  });
  const found = useCatalogSearch(search);
  const rows = search.trim() ? (found.data ?? []) : (listed.data ?? []);
  return (
    <>
      <PageHeader
        title={title}
        description={t('catalog_admin.intro')}
        extra={
          <Space wrap>
            <Button
              icon={<PlusOutlined />}
              onClick={() => {
                setDialog({});
              }}
              data-testid="cat-new-category"
            >
              {t('catalog_admin.new_category')}
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => void navigate('/admin/catalog/items/new')}
              data-testid="cat-new-item"
            >
              {t('catalog_admin.new_item')}
            </Button>
          </Space>
        }
      />
      <StarterBanner />
      <Flex gap={16} align="flex-start" wrap>
        <Card
          size="small"
          title={t('catalog_admin.categories')}
          style={{ flex: '0 1 300px', minWidth: 260 }}
          data-testid="cat-tree"
        >
          <CategoryTree
            categories={categories.data ?? []}
            selected={category}
            onSelect={setCategory}
            onEdit={(c) => {
              setDialog({ category: c });
            }}
            onAddChild={(parent) => {
              setDialog({ parent });
            }}
          />
        </Card>
        <Flex vertical gap={12} style={{ flex: '1 1 520px', minWidth: 0 }}>
          <Flex gap={12} wrap align="center">
            <Input.Search
              allowClear
              placeholder={t('catalog_admin.search')}
              aria-label={t('catalog_admin.search')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              style={{ maxWidth: 360 }}
              data-testid="cat-search"
            />
            <Segmented
              value={filter}
              onChange={(value) => {
                setFilter(value);
              }}
              options={FILTERS.map((f) => ({
                value: f,
                label: f === 'all' ? t('catalog_admin.all') : t(`catalog_item_status.${f}`),
              }))}
              disabled={search.trim() !== ''}
              data-testid="cat-filter"
            />
          </Flex>
          <ItemsTable
            rows={rows}
            categories={categories.data ?? []}
            loading={search.trim() ? found.isFetching : listed.isLoading}
            orderable={category !== null && filter === 'all' && !search.trim()}
          />
          <SettingsCard />
        </Flex>
      </Flex>
      {dialog !== null && (
        <CategoryDialog
          category={dialog.category}
          parentId={dialog.parent}
          categories={categories.data ?? []}
          onClose={() => {
            setDialog(null);
          }}
        />
      )}
    </>
  );
}

/** The tree: the root "All items", then each category with its own actions (plan D1, D11). */
function CategoryTree({
  categories,
  selected,
  onSelect,
  onEdit,
  onAddChild,
}: {
  categories: CatalogCategory[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  onEdit: (category: CatalogCategory) => void;
  onAddChild: (parentId: string) => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { token } = theme.useToken();
  const move = useUpdateCatalogCategory();
  const byParent = useMemo(() => childrenOf(categories), [categories]);

  const swap = (a: CatalogCategory, b: CatalogCategory) => {
    // Two writes, each with its own If-Match; a stale one says so (409) and the tree refetches.
    void (async () => {
      try {
        await move.mutateAsync({
          id: a.id,
          body: { sort_order: b.sort_order === a.sort_order ? a.sort_order + 1 : b.sort_order },
          version: a.version,
        });
        await move.mutateAsync({
          id: b.id,
          body: { sort_order: a.sort_order },
          version: b.version,
        });
      } catch (error) {
        reportError(error);
      }
    })();
  };

  const branch = (parent: string | null, depth: number): React.ReactNode[] =>
    (byParent.get(parent) ?? []).flatMap((c, index, siblings) => [
      <Flex
        key={c.id}
        align="center"
        gap={4}
        style={{
          paddingInlineStart: depth * 16,
          background: selected === c.id ? token.controlItemBgActive : undefined,
          borderRadius: 6,
        }}
        data-testid={`cat-node-${c.id}`}
      >
        <Button
          type="text"
          size="small"
          onClick={() => {
            onSelect(c.id);
          }}
          aria-current={selected === c.id}
          style={{ flex: 1, justifyContent: 'flex-start', minWidth: 0 }}
        >
          <Typography.Text ellipsis type={c.enabled ? undefined : 'secondary'} delete={!c.enabled}>
            {textIn(c.names, locale)}
          </Typography.Text>
        </Button>
        <Tooltip title={t('catalog_admin.move_up')}>
          <Button
            type="text"
            size="small"
            icon={<ArrowUpOutlined />}
            aria-label={t('catalog_admin.move_up')}
            disabled={index === 0 || move.isPending}
            onClick={() => {
              const before = siblings[index - 1];
              if (before) swap(c, before);
            }}
          />
        </Tooltip>
        <Tooltip title={t('catalog_admin.move_down')}>
          <Button
            type="text"
            size="small"
            icon={<ArrowDownOutlined />}
            aria-label={t('catalog_admin.move_down')}
            disabled={index === siblings.length - 1 || move.isPending}
            onClick={() => {
              const after = siblings[index + 1];
              if (after) swap(c, after);
            }}
          />
        </Tooltip>
        {depth < 3 && (
          <Tooltip title={t('catalog_admin.add_subcategory')}>
            <Button
              type="text"
              size="small"
              icon={<PlusOutlined />}
              aria-label={t('catalog_admin.add_subcategory')}
              onClick={() => {
                onAddChild(c.id);
              }}
            />
          </Tooltip>
        )}
        <Tooltip title={t('catalog_admin.edit_category')}>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            aria-label={t('catalog_admin.edit_category')}
            onClick={() => {
              onEdit(c);
            }}
            data-testid={`cat-edit-${c.id}`}
          />
        </Tooltip>
      </Flex>,
      ...branch(c.id, depth + 1),
    ]);

  return (
    <Flex vertical gap={2}>
      <Button
        type="text"
        size="small"
        onClick={() => {
          onSelect(null);
        }}
        aria-current={selected === null}
        style={{ justifyContent: 'flex-start' }}
        data-testid="cat-node-all"
      >
        {t('catalog_admin.all_items')}
      </Button>
      {branch(null, 0)}
      {categories.length === 0 && (
        <Typography.Text type="secondary">{t('catalog_admin.no_categories')}</Typography.Text>
      )}
    </Flex>
  );
}

function ItemsTable({
  rows,
  categories,
  loading,
  orderable,
}: {
  rows: CatalogItem[];
  categories: CatalogCategory[];
  loading: boolean;
  orderable: boolean;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const paths = useMemo(() => categoryPaths(categories, locale), [categories, locale]);
  const { token } = theme.useToken();
  const update = useUpdateCatalogItem();
  const copy = useCopyCatalogItem();
  const remove = useDeleteCatalogItem();
  const navigate = useNavigate();

  const swap = (a: CatalogItem, b: CatalogItem) => {
    void (async () => {
      try {
        await update.mutateAsync({
          id: a.id,
          body: { sort_order: b.sort_order === a.sort_order ? a.sort_order + 1 : b.sort_order },
          version: a.version,
        });
        await update.mutateAsync({
          id: b.id,
          body: { sort_order: a.sort_order },
          version: b.version,
        });
      } catch (error) {
        reportError(error);
      }
    })();
  };

  return (
    <Table<CatalogItem>
      rowKey="id"
      size="middle"
      loading={loading}
      dataSource={rows}
      pagination={false}
      locale={{ emptyText: t('catalog_admin.no_items') }}
      data-testid="cat-items"
      columns={[
        {
          key: 'name',
          title: t('catalog_admin.column.name'),
          render: (_, item) => (
            <Space size={6}>
              {item.featured && (
                <StarFilled
                  aria-label={t('catalog_admin.featured')}
                  style={{ color: token.colorWarningText }}
                />
              )}
              <Link to={`/admin/catalog/items/${item.id}`} data-testid={`cat-item-${item.id}`}>
                {textIn(item.names, locale)}
              </Link>
              {item.kind === 'incident_template' && (
                <ToneTag tone="info">{t('catalog_item_kind.incident_template')}</ToneTag>
              )}
            </Space>
          ),
        },
        {
          key: 'category',
          title: t('catalog_admin.column.category'),
          render: (_, item) =>
            item.category_id === null ? (
              <Typography.Text type="secondary">{t('catalog_admin.no_category')}</Typography.Text>
            ) : (
              (paths.get(item.category_id) ?? t('catalog_admin.no_category'))
            ),
        },
        {
          key: 'status',
          title: t('catalog_admin.column.status'),
          render: (_, item) => <StatusTag item={item} />,
        },
        {
          key: 'actions',
          title: <span className="sr-only">{t('catalog_admin.column.actions')}</span>,
          width: 200,
          render: (_, item, index) => (
            <Space size={0} wrap>
              {orderable && (
                <>
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowUpOutlined />}
                    aria-label={t('catalog_admin.move_up')}
                    disabled={index === 0 || update.isPending}
                    onClick={() => {
                      const before = rows[index - 1];
                      if (before) swap(item, before);
                    }}
                  />
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowDownOutlined />}
                    aria-label={t('catalog_admin.move_down')}
                    disabled={index === rows.length - 1 || update.isPending}
                    onClick={() => {
                      const after = rows[index + 1];
                      if (after) swap(item, after);
                    }}
                  />
                </>
              )}
              <Tooltip title={t('catalog_admin.copy')}>
                <Button
                  type="text"
                  size="small"
                  icon={<CopyOutlined />}
                  aria-label={t('catalog_admin.copy')}
                  data-testid={`cat-copy-${item.id}`}
                  onClick={() => {
                    copy.mutate(
                      { id: item.id, key: crypto.randomUUID() },
                      {
                        onSuccess: (made) => {
                          void message.success(t('catalog_admin.copied'));
                          void navigate(`/admin/catalog/items/${made.id}`);
                        },
                        onError: reportError,
                      },
                    );
                  }}
                />
              </Tooltip>
              <Popconfirm
                title={t('catalog_admin.delete_title')}
                description={t('catalog_admin.delete_text')}
                okText={t('actions.delete')}
                cancelText={t('actions.cancel')}
                okButtonProps={{ danger: true }}
                onConfirm={() => {
                  void remove
                    .mutateAsync({ id: item.id, version: item.version })
                    .catch((error: unknown) => {
                      if (error instanceof ApiError && error.code === 'catalog_item_in_use') {
                        markHandled(error);
                        void message.warning(t('errors.catalog_item_in_use'));
                        return;
                      }
                      reportError(error);
                    });
                }}
              >
                <Button
                  type="text"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  aria-label={t('actions.delete')}
                  data-testid={`cat-delete-${item.id}`}
                />
              </Popconfirm>
            </Space>
          ),
        },
      ]}
    />
  );
}

/** D-138: the starter items wait as drafts until the admin gives them a group. */
function StarterBanner() {
  const t = useLabel();
  const { message } = App.useApp();
  const starter = useCatalogStarter();
  const groups = useUnits('groups');
  const publish = usePublishCatalogStarter();
  const [group, setGroup] = useState<string | undefined>();
  const drafts = starter.data?.drafts ?? 0;
  if (drafts === 0) return null;
  return (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      data-testid="cat-starter"
      message={t('catalog_admin.starter.title', { count: drafts })}
      description={
        <Flex vertical gap={8}>
          <Typography.Text>{t('catalog_admin.starter.text')}</Typography.Text>
          <Flex gap={8} wrap>
            <Select
              style={{ minWidth: 240 }}
              placeholder={t('catalog_admin.starter.group')}
              aria-label={t('catalog_admin.starter.group')}
              value={group}
              onChange={setGroup}
              options={(groups.data ?? [])
                .filter((g) => !g.disabled)
                .map((g) => ({ value: g.id, label: g.name }))}
              data-testid="cat-starter-group"
            />
            <Button
              type="primary"
              disabled={group === undefined}
              loading={publish.isPending}
              data-testid="cat-starter-publish"
              onClick={() => {
                if (group === undefined) return;
                publish.mutate(group, {
                  onSuccess: (done) => {
                    void message.success(
                      t('catalog_admin.starter.done', {
                        count: done.published,
                        skipped: done.skipped.length,
                      }),
                    );
                  },
                  onError: reportError,
                });
              }}
            >
              {t('catalog_admin.starter.publish')}
            </Button>
          </Flex>
        </Flex>
      }
    />
  );
}

/** The tenant's catalog setting (plan D7): hide the default incident form from requesters. */
function SettingsCard() {
  const t = useLabel();
  const settings = useCatalogSettings();
  const change = useCatalogSettingsChange();
  const value = settings.data;
  return (
    <Card size="small" title={t('catalog_admin.settings')}>
      <Flex align="center" gap={12} justify="space-between">
        <Flex vertical>
          <Typography.Text strong>{t('catalog_admin.hide_default_incident')}</Typography.Text>
          <Typography.Text type="secondary">
            {t('catalog_admin.hide_default_incident_help')}
          </Typography.Text>
        </Flex>
        <Switch
          checked={value?.hide_default_incident_template ?? false}
          disabled={value === undefined}
          loading={change.isPending}
          aria-label={t('catalog_admin.hide_default_incident')}
          data-testid="cat-hide-default"
          onChange={(checked) => {
            if (value === undefined) return;
            change.mutate(
              { body: { hide_default_incident_template: checked }, version: value.version },
              { onError: reportError },
            );
          }}
        />
      </Flex>
    </Card>
  );
}
