import { useQueryClient } from '@tanstack/react-query';
import { App, Button, Flex, Input, Segmented, Table, TreeSelect } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  queryKeys,
  useCiStates,
  useCiTypes,
  useCis,
  useRestoreCi,
  type CiListItem,
} from '@supportx/api-client';
import { refreshList, refreshRecord, useListChannel, useTenantChannel } from '@supportx/realtime';
import {
  FilterBar,
  ListPage,
  NoAccess,
  NotInPlan,
  PageHeader,
  WriteButton,
  loadedEmpty,
  reportError,
  useAccess,
  useLicence,
  useAppearance,
  useLabel,
} from '@supportx/ui';

import { SEARCH_DELAY_MS, useDebounced } from '../../useDebounced';
import { nameOf, typeTree } from './names';
import { useCmdbRight } from './rights';

/**
 * The CMDB home (template C, D-147): the type tree as the first filter, a search by name, the
 * CI list or the trash; live (rule c) through the cmdb list channels.
 */
export function CmdbPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { locale, intlLocale } = useAppearance();
  const { can } = useAccess();
  const may = useCmdbRight();
  const { has, isAdmin } = useLicence();
  const allowed = can('cmdb.view');
  const [view, setView] = useState<'current' | 'trash'>('current');
  const [search, setSearch] = useState('');
  const [typeId, setTypeId] = useState<string>();
  const text = useDebounced(search.trim(), SEARCH_DELAY_MS);
  const trash = view === 'trash';
  const filter = useMemo(
    () => (text === '' ? undefined : { field: 'name', op: 'contains' as const, value: text }),
    [text],
  );
  const list = useCis({ filter, typeTree: trash ? undefined : typeId, trash }, allowed);
  const types = useCiTypes(allowed);
  const states = useCiStates(allowed);
  const queryClient = useQueryClient();
  const refresh = () => {
    refreshList(queryClient, [...queryKeys.cmdb.all, 'list']);
  };
  useListChannel(allowed ? 'cmdb' : null, (message) => {
    refresh();
    void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.types }); // the counts
    for (const id of message.ids) refreshRecord(queryClient, queryKeys.cmdb.detail(id), message);
  });
  useTenantChannel((message) => {
    if (message.type === 'refresh' || message.type === 'cmdb.config_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.all });
    }
  });

  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.items) ?? [], [list.data]);
  const typeName = useMemo(() => {
    const found = new Map(
      (types.data?.items ?? []).map((x) => [x.id, nameOf(t, locale, x, 'cmdb_ci_type')]),
    );
    return (id: string) => found.get(id) ?? '';
  }, [types.data, t, locale]);
  const stateName = useMemo(() => {
    const found = new Map(
      (states.data?.items ?? []).map((x) => [x.id, nameOf(t, locale, x, 'cmdb_ci_state')]),
    );
    return (id: string) => found.get(id) ?? '';
  }, [states.data, t, locale]);
  const tree = useMemo(
    () => typeTree(types.data?.items ?? [], (x) => nameOf(t, locale, x, 'cmdb_ci_type')),
    [types.data, t, locale],
  );
  if (!has('cmdb')) return <NotInPlan titleKey="nav.cmdb" isAdmin={isAdmin} />;
  if (!allowed) return <NoAccess titleKey="nav.cmdb" />;
  const dateFormat = new Intl.DateTimeFormat(intlLocale, { dateStyle: 'medium' });

  return (
    <ListPage
      testId="cmdb-list"
      header={
        <PageHeader
          title={t('cmdb.title')}
          extra={
            <Flex gap={8} wrap>
              {may('configure') && (
                <Button onClick={() => void navigate('/admin/cmdb')} data-testid="cmdb-types">
                  {t('cmdb.title.types')}
                </Button>
              )}
              {may('add') && (
                <WriteButton
                  type="primary"
                  onClick={() => void navigate('/cmdb/new')}
                  data-testid="cmdb-new"
                >
                  {t('cmdb.action.new_ci')}
                </WriteButton>
              )}
            </Flex>
          }
        />
      }
      filters={
        <FilterBar
          testId="cmdb-filters"
          view={
            <Segmented<'current' | 'trash'>
              value={view}
              onChange={setView}
              options={[
                { value: 'current', label: t('cmdb.view.current') },
                { value: 'trash', label: t('cmdb.view.trash') },
              ]}
              data-testid="cmdb-view"
            />
          }
          search={
            <Input.Search
              allowClear
              aria-label={t('cmdb.field.name')}
              placeholder={t('cmdb.field.name')}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
              }}
              data-testid="cmdb-search"
            />
          }
          quick={
            !trash && (
              <TreeSelect
                aria-label={t('cmdb.field.type_id')}
                allowClear
                treeDefaultExpandAll
                placeholder={t('cmdb.all_types')}
                value={typeId}
                onChange={(value: string | undefined) => {
                  setTypeId(value);
                }}
                treeData={tree}
                style={{ minWidth: 240 }}
                data-testid="cmdb-type-tree"
              />
            )
          }
        />
      }
    >
      <div role="region" aria-label={t('cmdb.title')} tabIndex={0} style={{ overflowX: 'auto' }}>
        <Table<CiListItem>
          rowKey="id"
          data-testid="cmdb-table"
          loading={list.isPending && list.fetchStatus === 'fetching'}
          dataSource={rows}
          pagination={false}
          locale={{ emptyText: loadedEmpty(list.isPending, t('cmdb.empty')) }}
          columns={[
            {
              key: 'id',
              title: t('cmdb.field.display_id'),
              width: 1,
              render: (_, row) => {
                const id = <bdi style={{ whiteSpace: 'nowrap' }}>{row.display_id}</bdi>;
                return trash ? id : <Link to={`/cmdb/${row.id}`}>{id}</Link>;
              },
            },
            { key: 'name', title: t('cmdb.field.name'), render: (_, row) => <bdi>{row.name}</bdi> },
            {
              key: 'type',
              title: t('cmdb.field.type_id'),
              render: (_, row) => typeName(row.type_id),
            },
            {
              key: 'state',
              title: t('cmdb.field.state_id'),
              render: (_, row) => stateName(row.state_id),
            },
            {
              key: 'impact',
              title: t('cmdb.field.business_impact'),
              render: (_, row) =>
                row.business_impact === null ? '' : t(`cmdb_impact.${row.business_impact}`),
            },
            {
              key: 'updated',
              title: t('cmdb.field.updated_at'),
              width: 1,
              render: (_, row) => (
                <span style={{ whiteSpace: 'nowrap' }}>
                  {dateFormat.format(new Date(row.updated_at))}
                </span>
              ),
            },
            ...(trash && may('delete')
              ? [
                  {
                    key: 'restore',
                    title: t('cmdb.field.restore'),
                    render: (_: unknown, row: CiListItem) => <RestoreButton row={row} />,
                  },
                ]
              : []),
          ]}
        />
      </div>
      {list.hasNextPage && (
        <Flex justify="center">
          <Button onClick={() => void list.fetchNextPage()} loading={list.isFetchingNextPage}>
            {t('cmdb.more')}
          </Button>
        </Flex>
      )}
    </ListPage>
  );
}

function RestoreButton({ row }: { row: CiListItem }) {
  const t = useLabel();
  const { message } = App.useApp();
  const restore = useRestoreCi();
  return (
    <WriteButton
      size="small"
      loading={restore.isPending}
      onClick={() => {
        restore.mutate(
          { id: row.id, version: row.version },
          {
            onSuccess: () => void message.success(t('cmdb.restored', { id: row.display_id })),
            onError: reportError,
          },
        );
      }}
      data-testid={`cmdb-restore-${row.display_id}`}
    >
      {t('cmdb.action.restore')}
    </WriteButton>
  );
}
