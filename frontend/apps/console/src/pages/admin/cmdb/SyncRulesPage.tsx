import { PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { App, Flex, Input, Table } from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router';

import {
  queryKeys,
  useCiTypes,
  useDeleteSyncRule,
  useStartSyncRun,
  useSyncRules,
  type SyncRule,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  FilterBar,
  ListPage,
  NoAccess,
  PageHeader,
  RowActions,
  ToneTag,
  WriteButton,
  loadedEmpty,
  reportError,
  useAccess,
  useAppearance,
  useLabel,
  usePageCrumbs,
} from '@supportx/ui';

import { nameOf } from '../../cmdb/names';
import { SYNC_RULES_PATH, syncRuleHref } from './syncShared';

/**
 * Admin › CMDB › Sync rules (WP-053 S4a, REQ-CMDB-015; template A): which assets become CIs of
 * which type. Each rule is on or off and runs hourly, when an asset changes, or on demand. Live:
 * a change by another admin, or a run that finishes, refetches the list.
 */
export function SyncRulesPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const { message, modal } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const allowed = can('cmdb.configure');
  const rules = useSyncRules(allowed);
  const types = useCiTypes(allowed);
  const remove = useDeleteSyncRule();
  const start = useStartSyncRun();
  const [search, setSearch] = useState('');
  usePageCrumbs([
    { label: t('nav.admin_cmdb'), path: '/admin/cmdb' },
    { label: t('cmdb.sync.title') },
  ]);
  useTenantChannel(
    (m) => {
      if (m.covered === true) return; // a refresh: `covers` refetched it
      if (m.type === 'cmdb.sync_changed') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.cmdb.sync.all });
      }
    },
    { covers: [queryKeys.cmdb.sync.all] },
  );
  if (!allowed) return <NoAccess titleKey="cmdb.sync.title" />;
  const text = search.trim().toLocaleLowerCase();
  const rows = (rules.data?.items ?? []).filter(
    (r) => text === '' || r.name.toLocaleLowerCase().includes(text),
  );
  const typeName = (id: string) => {
    const found = types.data?.items.find((x) => x.id === id);
    return found === undefined
      ? t('cmdb.sync.removed_type')
      : nameOf(t, locale, found, 'cmdb_ci_type');
  };
  return (
    <ListPage
      testId="cmdb-sync-rules"
      header={
        <PageHeader
          title={t('cmdb.sync.title')}
          description={t('cmdb.sync.description')}
          count={rules.data === undefined ? undefined : String(rows.length)}
          testId="cmdb-sync-header"
          extra={
            <WriteButton
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => void navigate(`${SYNC_RULES_PATH}/new`)}
              data-testid="cmdb-sync-add"
            >
              {t('cmdb.sync.add')}
            </WriteButton>
          }
        />
      }
      filters={
        <FilterBar
          testId="cmdb-sync-filters"
          search={
            <Input.Search
              allowClear
              aria-label={t('cmdb.sync.search')}
              placeholder={t('cmdb.sync.search')}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
              }}
              data-testid="cmdb-sync-search"
            />
          }
        />
      }
    >
      <Table<SyncRule>
        rowKey="id"
        data-testid="cmdb-sync-table"
        loading={rules.isPending}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 640 }}
        locale={{
          emptyText: loadedEmpty(
            rules.isPending,
            t(text === '' ? 'cmdb.sync.empty' : 'cmdb.sync.no_match'),
          ),
        }}
        columns={[
          {
            key: 'name',
            title: t('cmdb.sync.name'),
            render: (_, r) => (
              <Link to={syncRuleHref(r.id)} data-testid={`cmdb-sync-link-${r.id}`}>
                <bdi dir="auto">{r.name}</bdi>
              </Link>
            ),
          },
          {
            key: 'type',
            title: t('cmdb.sync.target_type'),
            render: (_, r) => <bdi dir="auto">{typeName(r.target_type_id)}</bdi>,
          },
          {
            key: 'state',
            title: t('cmdb.sync.state'),
            render: (_, r) =>
              r.enabled ? (
                <ToneTag tone="success">{t('cmdb.sync.on')}</ToneTag>
              ) : (
                <ToneTag tone="default">{t('cmdb.sync.off')}</ToneTag>
              ),
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('settings.actions')}</span>,
            align: 'end' as const,
            render: (_, r) => (
              <RowActions
                rowName={r.name}
                primary={{
                  key: 'open',
                  label: t('cmdb.sync.open'),
                  onClick: () => void navigate(syncRuleHref(r.id)),
                  testId: `cmdb-sync-open-${r.id}`,
                }}
                more={[
                  {
                    key: 'run',
                    label: t('cmdb.sync.run_now'),
                    onClick: () => {
                      start.mutate(
                        { ruleId: r.id, key: crypto.randomUUID() },
                        {
                          onSuccess: () => void message.success(t('cmdb.sync.run_queued')),
                          onError: reportError,
                        },
                      );
                    },
                    testId: `cmdb-sync-run-${r.id}`,
                  },
                  {
                    key: 'delete',
                    label: t('actions.delete'),
                    danger: true,
                    onClick: () => {
                      void modal.confirm({
                        title: t('cmdb.sync.delete_title', { name: r.name }),
                        content: t('cmdb.sync.delete_body'),
                        okButtonProps: { danger: true },
                        okText: t('actions.delete'),
                        cancelText: t('actions.cancel'),
                        onOk: () =>
                          remove.mutateAsync({ id: r.id, version: r.version }).then(() => {
                            void message.success(t('cmdb.sync.deleted'));
                          }, reportError),
                      });
                    },
                    testId: `cmdb-sync-delete-${r.id}`,
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </ListPage>
  );
}

/** The sync rules entry on the CMDB setup page. */
export function SyncRulesLink() {
  const t = useLabel();
  return (
    <Flex gap={8} align="center" wrap>
      <Link to={SYNC_RULES_PATH} data-testid="cmdb-sync-rules-link">
        {t('cmdb.sync.title')}
      </Link>
    </Flex>
  );
}
