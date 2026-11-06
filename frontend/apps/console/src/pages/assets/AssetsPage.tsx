import { useQueryClient } from '@tanstack/react-query';
import { Button, Drawer, Flex, Input, Segmented, Table, Tag, TreeSelect, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  queryKeys,
  useAssetProductTypes,
  useAssetRecordChange,
  useAssetRecords,
  useAssetStates,
  type AssetRecord,
} from '@supportx/api-client';
import { refreshList, useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  EmptyText,
  NoAccess,
  PageHeader,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { useDebounced } from '../../useDebounced';
import { Problems } from '../admin/incidents/shared';
import { nameOf } from '../admin/assets/shared';
import { typeTree, type TypeNode } from '../admin/assets/tree';
import { BulkMoveDialog } from './AssetActions';
import { AssetFields } from './AssetForm';
import { bodyOf, draftOf, type AssetDraft } from './draft';
import { useAssetSaveProblems } from './problems';

/**
 * The asset list (WP-049a s2): search by name or any identifier, one product type, the trash.
 * It follows the asset list channel live (and the catalogue broadcast for names), so another
 * person's change shows without a refresh.
 */
const BULK_MAX = 100; // the API takes up to 100 assets per bulk move

export function AssetsPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const access = useAccess();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const allowed = access.can('assets.view');
  const [search, setSearch] = useState('');
  const [typeId, setTypeId] = useState<string>();
  const [view, setView] = useState<'live' | 'trash'>('live');
  const debounced = useDebounced(search, 300);
  const list = useAssetRecords(
    { search: debounced, productTypeId: typeId, trash: view === 'trash' },
    allowed,
  );
  const types = useAssetProductTypes(allowed);
  const states = useAssetStates(allowed);
  const change = useAssetRecordChange();
  const { problems, show, clear } = useAssetSaveProblems();
  const [adding, setAdding] = useState<{ draft: AssetDraft; key: string }>();
  useListChannel(allowed ? 'assets' : null, () => {
    refreshList(queryClient, [...queryKeys.assets.all, 'records']);
  });
  useTenantChannel((message) => {
    if (message.type === 'assets.catalogue_changed' || message.type === 'refresh') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.assets.all });
    }
  });
  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.items) ?? [], [list.data]);
  // Bulk moves (WP-049a s3): pick rows, move them to one state; the server checks each one.
  const bulkAllowed = view === 'live' && access.can('assets.manage');
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const selectedRows = useMemo(
    () => rows.filter((row) => selected.includes(row.id)),
    [rows, selected],
  );
  const tree = useMemo(() => typeTree(types.data ?? []), [types.data]);
  if (!allowed) return <NoAccess titleKey="nav.assets" />;
  const typeName = (id: string) => {
    const found = types.data?.find((x) => x.id === id);
    return found === undefined ? '' : nameOf(found.names, locale);
  };
  const stateName = (id: string) => {
    const found = states.data?.find((x) => x.id === id);
    return found === undefined ? '' : nameOf(found.names, locale);
  };
  const choices = (nodes: TypeNode[]): object[] =>
    nodes.map((node) => ({
      value: node.id,
      title: nameOf(node.names, locale),
      children: choices(node.children ?? []),
    }));
  const save = () => {
    if (adding === undefined) return;
    clear();
    change.mutate(
      { kind: 'create', key: adding.key, body: bodyOf(adding.draft) as never },
      {
        onSuccess: (made) => {
          setAdding(undefined);
          if (made !== undefined) void navigate(`/assets/${made.id}`);
        },
        onError: show,
      },
    );
  };
  return (
    <Flex vertical gap={16}>
      <PageHeader
        title={t('nav.assets')}
        extra={
          <Flex gap={8}>
            <Link to="/assets/vendors" data-testid="assets-vendors-link">
              {t('assets.record.vendors')}
            </Link>
            {access.can('assets.manage') && (
              <WriteButton
                type="primary"
                onClick={() => {
                  clear();
                  setAdding({ draft: draftOf(null), key: crypto.randomUUID() });
                }}
                data-testid="asset-add"
              >
                {t('assets.record.add')}
              </WriteButton>
            )}
          </Flex>
        }
      />
      <Flex gap={8} wrap align="center">
        <Input.Search
          allowClear
          aria-label={t('assets.record.search')}
          placeholder={t('assets.record.search')}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
          }}
          style={{ maxWidth: 320 }}
          data-testid="assets-search"
        />
        <TreeSelect
          aria-label={t('assets.admin.product_type')}
          allowClear
          placeholder={t('assets.admin.all_types')}
          value={typeId}
          treeData={choices(tree)}
          onChange={(id: string | undefined) => {
            setTypeId(id);
          }}
          style={{ minWidth: 220 }}
          data-testid="assets-type-filter"
        />
        {access.can('assets.manage') && (
          <Segmented
            value={view}
            onChange={(value) => {
              setView(value as 'live' | 'trash');
            }}
            options={[
              { value: 'live', label: t('assets.record.all') },
              { value: 'trash', label: t('assets.record.trash') },
            ]}
            data-testid="assets-view"
          />
        )}
        {bulkAllowed && selected.length > 0 && (
          <Flex gap={8} align="center" data-testid="assets-selection">
            <Typography.Text>
              {t('assets.bulk_move.selected', { count: selected.length })}
            </Typography.Text>
            <WriteButton
              onClick={() => {
                setBulkOpen(true);
              }}
              data-testid="assets-bulk-move-open"
            >
              {t('assets.bulk_move.open')}
            </WriteButton>
          </Flex>
        )}
      </Flex>
      <BulkMoveDialog
        assets={selectedRows}
        open={bulkOpen}
        onClose={() => {
          setBulkOpen(false);
          setSelected([]);
        }}
      />
      <Table<AssetRecord>
        size="small"
        rowKey="id"
        rowSelection={
          bulkAllowed
            ? {
                selectedRowKeys: selected,
                onChange: (keys) => {
                  setSelected(keys.map(String).slice(0, BULK_MAX));
                },
              }
            : undefined
        }
        pagination={false}
        loading={list.isLoading}
        dataSource={rows}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyText>{t('assets.record.none')}</EmptyText> }}
        onRow={(asset) => ({
          onClick: () => {
            if (view === 'live') void navigate(`/assets/${asset.id}`);
          },
          style: { cursor: view === 'live' ? 'pointer' : undefined },
        })}
        columns={[
          {
            key: 'tag',
            title: t('assets.record.tag'),
            render: (_: unknown, asset: AssetRecord) => (
              <bdi dir="ltr" data-testid={`asset-row-${asset.id}`}>
                {asset.tag ?? ''}
              </bdi>
            ),
          },
          {
            key: 'name',
            title: t('assets.record.name'),
            render: (_: unknown, asset: AssetRecord) => <bdi dir="auto">{asset.name}</bdi>,
          },
          {
            key: 'type',
            title: t('assets.admin.product_type'),
            render: (_: unknown, asset: AssetRecord) => (
              <bdi dir="auto">{typeName(asset.product_type_id)}</bdi>
            ),
          },
          {
            key: 'state',
            title: t('assets.record.state'),
            render: (_: unknown, asset: AssetRecord) => <Tag>{stateName(asset.state_id)}</Tag>,
          },
          {
            key: 'serial',
            title: t('assets.record.serial_number'),
            render: (_: unknown, asset: AssetRecord) => (
              <bdi dir="ltr">{asset.serial_number ?? ''}</bdi>
            ),
          },
          ...(view === 'trash'
            ? [
                {
                  key: 'restore',
                  title: <span className="sr-only">{t('assets.admin.actions')}</span>,
                  render: (_: unknown, asset: AssetRecord) => (
                    <WriteButton
                      type="link"
                      onClick={(event) => {
                        event.stopPropagation();
                        change.mutate({ kind: 'restore', id: asset.id }, { onError: reportError });
                      }}
                      data-testid={`asset-restore-${asset.id}`}
                    >
                      {t('assets.record.restore')}
                    </WriteButton>
                  ),
                },
              ]
            : []),
        ]}
      />
      {list.hasNextPage && (
        <Button
          onClick={() => {
            void list.fetchNextPage();
          }}
          loading={list.isFetchingNextPage}
          style={{ alignSelf: 'center' }}
        >
          {t('assets.admin.load_more')}
        </Button>
      )}
      <Drawer
        open={adding !== undefined}
        title={t('assets.record.add')}
        width={640}
        destroyOnHidden
        onClose={() => {
          setAdding(undefined);
        }}
        extra={
          <WriteButton
            type="primary"
            loading={change.isPending}
            onClick={save}
            data-testid="asset-add-save"
          >
            {t('actions.save')}
          </WriteButton>
        }
        data-testid="asset-add-drawer"
      >
        <Problems problems={problems} testId="asset-add-problems" />
        {adding !== undefined && (
          <AssetFields
            creating
            draft={adding.draft}
            onChange={(draft) => {
              setAdding({ ...adding, draft });
            }}
          />
        )}
      </Drawer>
    </Flex>
  );
}
